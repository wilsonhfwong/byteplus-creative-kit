//go:build !windows

package main

import "path/filepath"

func physicalDirectory(path string) (string, error) {
	physical, err := filepath.EvalSymlinks(path)
	if err != nil {
		return "", err
	}
	return filepath.Abs(physical)
}
