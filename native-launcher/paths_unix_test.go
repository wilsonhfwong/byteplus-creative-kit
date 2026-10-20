//go:build !windows

package main

import (
	"os"
	"testing"
)

func makeDirectoryLink(t *testing.T, link, target string) {
	t.Helper()
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
}
