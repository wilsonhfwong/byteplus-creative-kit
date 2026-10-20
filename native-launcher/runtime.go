package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

const uvVersion = "0.12.5"

type distribution struct{ file, sha256 string }

var distributions = map[string]distribution{
	"darwin/arm64":  {"uv-aarch64-apple-darwin.tar.gz", "5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62"},
	"darwin/amd64":  {"uv-x86_64-apple-darwin.tar.gz", "b3b2137477cf96c9686ebfb71524614cec780c673fd73e59bce099aef02e70e8"},
	"windows/amd64": {"uv-x86_64-pc-windows-msvc.zip", "4c4d49d8738847d9b71ba319e49a5688c93eac0fe6204b1df24e98528dddf39a"},
}

func (a *application) beginPrepare() {
	a.mu.Lock()
	if a.preparing || a.ready() {
		a.mu.Unlock()
		return
	}
	a.preparing = true
	a.prepareError = ""
	a.mu.Unlock()
	go func() {
		err := a.prepareRuntime()
		a.mu.Lock()
		defer a.mu.Unlock()
		a.preparing = false
		if err != nil {
			a.prepareError = "运行环境准备失败。请检查 GitHub、PyPI 的网络访问，再打开配置页面重试。"
		}
	}()
}

func (a *application) prepareRuntime() error {
	if err := os.MkdirAll(a.environment, 0700); err != nil {
		return err
	}
	lock := filepath.Join(a.environment, "bootstrap.lock")
	deadline := time.Now().Add(12 * time.Minute)
	for {
		if a.ready() {
			return nil
		}
		err := os.Mkdir(lock, 0700)
		if err == nil {
			break
		}
		if !os.IsExist(err) {
			return err
		}
		if info, e := os.Stat(lock); e == nil && time.Since(info.ModTime()) > 15*time.Minute {
			_ = os.Remove(lock)
			continue
		}
		if time.Now().After(deadline) {
			return errors.New("another runtime preparation is still in progress")
		}
		time.Sleep(time.Second)
	}
	defer os.Remove(lock)
	uv := filepath.Join(a.data, "bin", "uv-"+uvVersion)
	if runtime.GOOS == "windows" {
		uv += ".exe"
	}
	if _, err := os.Stat(uv); os.IsNotExist(err) {
		if err = installUV(uv); err != nil {
			return err
		}
	}
	log, err := os.OpenFile(filepath.Join(a.data, "runtime-install.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if err != nil {
		return err
	}
	defer log.Close()
	command := exec.Command(uv, "sync", "--directory", a.root, "--locked", "--no-dev", "--python", "3.12", "--managed-python")
	// Keep the interpreter with this version's virtual environment. An older
	// shared Python folder may contain a dangling logical-AppData junction;
	// leave it untouched instead of inspecting it or rewriting user settings.
	command.Env = append(os.Environ(), "UV_CACHE_DIR="+filepath.Join(a.data, "cache"), "UV_PYTHON_INSTALL_DIR="+filepath.Join(a.environment, "python"), "UV_PROJECT_ENVIRONMENT="+filepath.Join(a.environment, "venv"), "UV_NO_PROGRESS=1", "PYTHON_DOTENV_DISABLED=1")
	command.Stdout, command.Stderr = log, log
	hideWindow(command)
	if err = command.Run(); err != nil {
		return err
	}
	if _, err = os.Stat(a.python()); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(a.environment, "ready"), []byte(version+"\n"), 0600)
}

func installUV(target string) error {
	d, ok := distributions[runtime.GOOS+"/"+runtime.GOARCH]
	if !ok {
		return errors.New("this desktop platform is not supported")
	}
	client := &http.Client{Timeout: 3 * time.Minute, CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if req.URL.Scheme != "https" || len(via) > 10 {
			return errors.New("invalid download redirect")
		}
		return nil
	}}
	response, err := client.Get("https://github.com/astral-sh/uv/releases/download/" + uvVersion + "/" + d.file)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return errors.New("runtime download failed")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 80*1024*1024+1))
	if err != nil || len(data) > 80*1024*1024 {
		return errors.New("runtime download is incomplete or too large")
	}
	digest := sha256.Sum256(data)
	if hex.EncodeToString(digest[:]) != d.sha256 {
		return errors.New("runtime checksum mismatch")
	}
	binary, err := extractedUV(data, strings.HasSuffix(d.file, ".zip"))
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(target), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(target), ".uv-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if err = f.Chmod(0700); err == nil {
		_, err = f.Write(binary)
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), target)
}

func extractedUV(data []byte, zipped bool) ([]byte, error) {
	// Read just the named executable; never extract arbitrary archive paths.
	if zipped {
		archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
		if err != nil {
			return nil, err
		}
		for _, f := range archive.File {
			if filepath.Base(f.Name) != "uv.exe" {
				continue
			}
			r, err := f.Open()
			if err != nil {
				return nil, err
			}
			defer r.Close()
			return io.ReadAll(io.LimitReader(r, 80*1024*1024))
		}
	} else {
		gz, err := gzip.NewReader(bytes.NewReader(data))
		if err != nil {
			return nil, err
		}
		defer gz.Close()
		archive := tar.NewReader(gz)
		for {
			f, err := archive.Next()
			if err == io.EOF {
				break
			}
			if err != nil {
				return nil, err
			}
			if filepath.Base(f.Name) == "uv" && f.Typeflag == tar.TypeReg {
				return io.ReadAll(io.LimitReader(archive, 80*1024*1024))
			}
		}
	}
	return nil, errors.New("runtime executable is absent from archive")
}
