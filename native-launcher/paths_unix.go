//go:build !windows

package main

import (
	"os"
	"path/filepath"
)

func openMigrationFile(path string) (*os.File, error) { return os.Open(path) }

func physicalDirectory(path string) (string, error) {
	physical, err := filepath.EvalSymlinks(path)
	if err != nil {
		return "", err
	}
	return filepath.Abs(physical)
}
