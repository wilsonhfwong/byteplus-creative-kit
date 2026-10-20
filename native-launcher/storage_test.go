package main

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func windowsStorageFixture(t *testing.T) storageOptions {
	t.Helper()
	home := t.TempDir()
	config := filepath.Join(home, "AppData", "Roaming")
	if err := os.MkdirAll(config, 0700); err != nil {
		t.Fatal(err)
	}
	return storageOptions{windows: true, home: home, config: config, appDataRoots: []string{filepath.Join(home, "AppData")}}
}

func TestWindowsAliasIntoAppDataIsNotUsed(t *testing.T) {
	options := windowsStorageFixture(t)
	options.override = filepath.Join(options.home, "custom-alias")
	makeDirectoryLink(t, options.override, options.config)
	location, err := chooseStorage(options)
	if err != nil || location.data != resolvedOrOriginal(filepath.Join(options.home, ".byteplus-creative-kit")) {
		t.Fatalf("AppData alias was used: %+v / %v", location, err)
	}
}

func TestExplicitOutsideFolderDoesNotImportAnotherAccount(t *testing.T) {
	options := windowsStorageFixture(t)
	options.override = filepath.Join(options.home, "my-custom-profile")
	location, err := chooseStorage(options)
	if err != nil || location.data != resolvedOrOriginal(options.override) || len(location.legacy) != 0 {
		t.Fatalf("custom outside profile was changed: %+v / %v", location, err)
	}
}

func TestMacStorageLocationIsUnchanged(t *testing.T) {
	options := storageOptions{home: t.TempDir(), config: t.TempDir()}
	location, err := chooseStorage(options)
	if err != nil || location.data != filepath.Join(options.config, "BytePlusCreativeKit") || len(location.legacy) != 0 {
		t.Fatalf("Mac default changed: %+v / %v", location, err)
	}
}

func migrationFixture(t *testing.T) (storageLocation, string) {
	t.Helper()
	source := t.TempDir()
	location := storageLocation{data: filepath.Join(t.TempDir(), ".byteplus-creative-kit"), legacy: []string{source}}
	for name, data := range map[string]string{"settings.json": `{"api_key":"synthetic-migration-key","project":"migration-account"}`, "library.sqlite3": "synthetic database snapshot"} {
		if err := os.WriteFile(filepath.Join(source, name), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return location, source
}

func TestMigrationRetainsStateAndLeavesOldRuntimeBehind(t *testing.T) {
	location, source := migrationFixture(t)
	if err := os.MkdirAll(filepath.Join(source, "python"), 0700); err != nil {
		t.Fatal(err)
	}
	makeDirectoryLink(t, filepath.Join(source, "python", "broken"), filepath.Join(source, "missing"))
	if err := migrateStorage(location); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"settings.json", "library.sqlite3"} {
		before, _ := os.ReadFile(filepath.Join(source, name))
		after, err := os.ReadFile(filepath.Join(location.data, name))
		if err != nil || string(before) != string(after) {
			t.Fatalf("state was not preserved: %s / %v", name, err)
		}
	}
	if _, err := os.Stat(filepath.Join(location.data, "python")); !os.IsNotExist(err) {
		t.Fatal("migration copied the broken runtime")
	}
	if err := os.WriteFile(filepath.Join(location.data, "settings.json"), []byte(`{"api_key":"newer-local-account"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := migrateStorage(location); err != nil {
		t.Fatal(err)
	}
	current, _ := os.ReadFile(filepath.Join(location.data, "settings.json"))
	if string(current) != `{"api_key":"newer-local-account"}` {
		t.Fatal("repeat startup overwrote the new account")
	}
}

func TestMigrationDoesNotPublishPartialStateWithActiveDatabase(t *testing.T) {
	location, source := migrationFixture(t)
	if err := os.WriteFile(filepath.Join(source, "library.sqlite3-wal"), []byte("uncommitted"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := migrateStorage(location); err == nil {
		t.Fatal("migration accepted an unfinished database")
	}
	if _, err := os.Stat(location.data); !os.IsNotExist(err) {
		t.Fatal("failed migration published partial credentials")
	}
}

func TestWindowsMigrationDoesNotCopyAnOpenWritableDatabase(t *testing.T) {
	if runtime.GOOS != "windows" {
		t.Skip("Windows sharing-mode protection")
	}
	location, source := migrationFixture(t)
	writer, err := os.OpenFile(filepath.Join(source, "library.sqlite3"), os.O_RDWR, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Close()
	if err := migrateStorage(location); err == nil {
		t.Fatal("copied a database while a writer still had it open")
	}
}

func TestWindowsDefaultStorageIsInUserFolder(t *testing.T) {
	options := windowsStorageFixture(t)
	location, err := chooseStorage(options)
	if err != nil {
		t.Fatal(err)
	}
	if want := resolvedOrOriginal(filepath.Join(options.home, ".byteplus-creative-kit")); location.data != want {
		t.Fatalf("Windows still selects AppData: got %q, want %q", location.data, want)
	}
}

func TestWindowsOldRepairOverrideCannotKeepUsingAppData(t *testing.T) {
	options := windowsStorageFixture(t)
	options.override = filepath.Join(options.home, "AppData", "Local", "Packages", "OldHost", "LocalCache", "Roaming", "BytePlusCreativeKit")
	location, err := chooseStorage(options)
	if err != nil {
		t.Fatal(err)
	}
	if want := resolvedOrOriginal(filepath.Join(options.home, ".byteplus-creative-kit")); location.data != want {
		t.Fatalf("repair override still writes into AppData: got %q, want %q", location.data, want)
	}
}
