package main

import (
	"os/exec"
	"testing"
)

func makeDirectoryLink(t *testing.T, link, target string) {
	t.Helper()
	// Directory junctions do not need Windows Developer Mode or symlink rights.
	if output, err := exec.Command("cmd", "/c", "mklink", "/J", link, target).CombinedOutput(); err != nil {
		t.Fatalf("create test junction: %v\n%s", err, output)
	}
}
