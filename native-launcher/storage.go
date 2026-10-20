package main

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type storageOptions struct {
	windows                bool
	home, config, override string
	appDataRoots           []string
}

type storageLocation struct {
	data   string
	legacy []string
}

func chooseStorage(options storageOptions) (storageLocation, error) {
	data := options.override
	if data == "" {
		data = filepath.Join(options.config, "BytePlusCreativeKit")
	}
	if !options.windows {
		return storageLocation{data: data}, nil
	}
	legacy := []string{}
	if options.override != "" {
		legacy = append(legacy, options.override)
	}
	if options.config != "" {
		legacy = append(legacy, filepath.Join(options.config, "BytePlusCreativeKit"))
	}
	redirected := options.override == "" || insideAppData(options.override, options.appDataRoots)
	if redirected {
		data = filepath.Join(options.home, ".byteplus-creative-kit")
	}
	physical, err := prospectiveDirectory(data)
	if err != nil {
		return storageLocation{}, err
	}
	if insideAppData(physical, options.appDataRoots) {
		redirected = true
		// Also reject an outside-looking override whose junction leads back
		// into AppData. Never redirect writes there through an alias.
		data = filepath.Join(options.home, ".byteplus-creative-kit")
		physical, err = prospectiveDirectory(data)
		if err != nil {
			return storageLocation{}, err
		}
		if insideAppData(physical, options.appDataRoots) {
			return storageLocation{}, errors.New("the Windows user data folder resolves into AppData")
		}
	}
	if !redirected {
		return storageLocation{data: physical}, nil
	}
	return storageLocation{data: physical, legacy: legacy}, nil
}

func insideAppData(path string, roots []string) bool {
	for _, root := range roots {
		if root == "" {
			continue
		}
		for _, candidate := range []string{root, resolvedOrOriginal(root)} {
			relative, err := filepath.Rel(strings.ToLower(filepath.Clean(candidate)), strings.ToLower(filepath.Clean(path)))
			if err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
				return true
			}
		}
	}
	return false
}

func resolvedOrOriginal(path string) string {
	resolved, err := prospectiveDirectory(path)
	if err != nil {
		return path
	}
	return resolved
}

func prospectiveDirectory(path string) (string, error) {
	ancestor, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	missing := []string{}
	for {
		if info, err := os.Stat(ancestor); err == nil {
			if !info.IsDir() {
				return "", errors.New("the data path is not a directory")
			}
			physical, err := physicalDirectory(ancestor)
			if err != nil {
				return "", err
			}
			for i := len(missing) - 1; i >= 0; i-- {
				physical = filepath.Join(physical, missing[i])
			}
			return physical, nil
		} else if !os.IsNotExist(err) {
			return "", err
		}
		missing = append(missing, filepath.Base(ancestor))
		parent := filepath.Dir(ancestor)
		if parent == ancestor {
			return "", errors.New("the data path has no existing parent")
		}
		ancestor = parent
	}
}

// Copy only durable state. Runtime binaries, environments, caches, logs and
// stale Python junctions are rebuilt outside AppData, never migrated.
func migrateStorage(location storageLocation) error {
	if _, err := os.Stat(location.data); err == nil {
		return nil // An existing destination is authoritative; never overwrite it.
	} else if !os.IsNotExist(err) {
		return err
	}
	for _, source := range location.legacy {
		if strings.EqualFold(filepath.Clean(source), filepath.Clean(location.data)) {
			continue
		}
		files := []string{}
		for _, name := range []string{"settings.json", "library.sqlite3"} {
			info, err := os.Lstat(filepath.Join(source, name))
			if os.IsNotExist(err) {
				continue
			}
			if err != nil {
				return errors.New("cannot read the previous kit settings; close the previous app and retry")
			}
			if !info.Mode().IsRegular() {
				return errors.New("the previous kit state is not an ordinary file")
			}
			files = append(files, name)
		}
		if len(files) == 0 {
			continue
		}
		if err := stageStorageMigration(source, location.data, files); err != nil {
			return err
		}
		return nil // Never combine credentials and records from different accounts.
	}
	return nil
}

func stageStorageMigration(source, destination string, names []string) error {
	parent := filepath.Dir(destination)
	if err := os.MkdirAll(parent, 0700); err != nil {
		return err
	}
	stage, err := os.MkdirTemp(parent, ".byteplus-migration-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(stage)
	for _, name := range names {
		if err := copyStateFile(source, stage, name); err != nil {
			return err
		}
	}
	if err := os.Rename(stage, destination); err != nil {
		if _, existing := os.Stat(destination); existing == nil {
			return nil // Another startup completed migration first.
		}
		return err
	}
	return nil
}

func copyStateFile(source, stage, name string) error {
	input, err := openMigrationFile(filepath.Join(source, name))
	if err != nil {
		return errors.New("the previous kit is still using its files; fully quit the previous app and retry")
	}
	defer input.Close()
	if name == "library.sqlite3" {
		for _, suffix := range []string{"-wal", "-journal", "-shm"} {
			if _, err := os.Stat(filepath.Join(source, name+suffix)); !os.IsNotExist(err) {
				return errors.New("the previous asset database has unfinished transactions; close the previous app before migration")
			}
		}
	}
	output, err := os.OpenFile(filepath.Join(stage, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(output, input)
	syncErr := output.Sync()
	closeErr := output.Close()
	if copyErr != nil || syncErr != nil || closeErr != nil {
		return errors.New("cannot copy the previous kit state into the user folder")
	}
	return nil
}
