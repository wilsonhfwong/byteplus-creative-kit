package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestMain(m *testing.M) {
	if os.Getenv("CREATIVE_KIT_TEST_UV") == "1" {
		// Stand in for uv at the real bootstrap subprocess boundary, without
		// downloading Python or dependencies. A dangling managed-version link
		// triggers the same failure as the customer's virtualized AppData path.
		pythonRoot := os.Getenv("UV_PYTHON_INSTALL_DIR")
		entries, _ := os.ReadDir(pythonRoot)
		for _, entry := range entries {
			path := filepath.Join(pythonRoot, entry.Name())
			if _, err := os.Stat(path); os.IsNotExist(err) {
				fmt.Fprintln(os.Stderr, "Missing expected target directory for Python minor version link at", path)
				os.Exit(2)
			}
		}
		venv := os.Getenv("UV_PROJECT_ENVIRONMENT")
		python := filepath.Join(venv, "bin", "python")
		if runtime.GOOS == "windows" {
			python = filepath.Join(venv, "Scripts", "python.exe")
		}
		if err := os.MkdirAll(filepath.Dir(python), 0700); err != nil {
			panic(err)
		}
		if err := os.WriteFile(python, []byte("bootstrap fixture"), 0700); err != nil {
			panic(err)
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}

func installFixtureUV(t *testing.T, a *application) {
	t.Helper()
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	name := "uv-" + uvVersion
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	target := filepath.Join(a.data, "bin", name)
	if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
		t.Fatal(err)
	}
	source, err := os.Open(executable)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	destination, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0700)
	if err != nil {
		t.Fatal(err)
	}
	_, copyErr := io.Copy(destination, source)
	closeErr := destination.Close()
	if copyErr != nil || closeErr != nil {
		t.Fatalf("copy uv fixture: %v / %v", copyErr, closeErr)
	}
	t.Setenv("CREATIVE_KIT_TEST_UV", "1")
}

func TestRuntimeRecoversFromLegacyDanglingPythonLink(t *testing.T) {
	a := testApplication(t)
	legacy := filepath.Join(a.data, "python")
	if err := os.MkdirAll(legacy, 0700); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(legacy, "cpython-3.12-windows-x86_64-none")
	// The logical target is absent, while the physical download still exists.
	physical := filepath.Join(legacy, "cpython-3.12.14-windows-x86_64-none")
	if err := os.MkdirAll(physical, 0700); err != nil {
		t.Fatal(err)
	}
	makeDirectoryLink(t, link, filepath.Join(t.TempDir(), "logical-AppData", filepath.Base(physical)))
	if err := a.saveSettings(map[string]string{"api_key": "synthetic-retained-key"}); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(a.settingsPath())
	installFixtureUV(t, a)
	if err := a.prepareRuntime(); err != nil {
		log, _ := os.ReadFile(filepath.Join(a.data, "runtime-install.log"))
		t.Fatalf("bootstrap still consumes the broken legacy link: %v\n%s", err, log)
	}
	if !a.ready() {
		t.Fatal("replacement runtime is not ready")
	}
	after, _ := os.ReadFile(a.settingsPath())
	if string(before) != string(after) {
		t.Fatal("runtime recovery changed credentials")
	}
	if _, err := os.Lstat(link); err != nil {
		t.Fatal("runtime recovery removed the old link")
	}
}

func TestDataDirectoryUsesPhysicalLocation(t *testing.T) {
	physical := t.TempDir()
	logical := filepath.Join(t.TempDir(), "logical-AppData")
	makeDirectoryLink(t, logical, physical)
	a, err := newApplication(t.TempDir(), logical)
	if err != nil {
		t.Fatal(err)
	}
	want, _ := filepath.EvalSymlinks(physical)
	if !strings.EqualFold(a.data, want) {
		t.Fatalf("runtime paths retain the logical alias: got %q, physical %q", a.data, want)
	}
}
