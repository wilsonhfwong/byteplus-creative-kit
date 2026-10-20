package main

import (
	"os"
	"strings"
	"syscall"
	"unsafe"
)

var getFinalPathNameByHandle = syscall.NewLazyDLL("kernel32.dll").NewProc("GetFinalPathNameByHandleW")

func physicalDirectory(path string) (string, error) {
	// os.Open supplies FILE_FLAG_BACKUP_SEMANTICS for directory handles.
	directory, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer directory.Close()
	buffer := make([]uint16, 260)
	for {
		n, _, callErr := getFinalPathNameByHandle.Call(directory.Fd(), uintptr(unsafe.Pointer(&buffer[0])), uintptr(len(buffer)), 0)
		if n == 0 {
			return "", os.NewSyscallError("GetFinalPathNameByHandleW", callErr)
		}
		if n >= uintptr(len(buffer)) {
			buffer = make([]uint16, n+1)
			continue
		}
		physical := syscall.UTF16ToString(buffer[:n])
		if strings.HasPrefix(physical, `\\?\UNC\`) {
			return `\\` + strings.TrimPrefix(physical, `\\?\UNC\`), nil
		}
		return strings.TrimPrefix(physical, `\\?\`), nil
	}
}
