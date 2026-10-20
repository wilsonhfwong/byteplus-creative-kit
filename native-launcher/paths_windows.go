package main

import (
	"os"
	"strings"
	"syscall"
	"unsafe"
)

var getFinalPathNameByHandle = syscall.NewLazyDLL("kernel32.dll").NewProc("GetFinalPathNameByHandleW")

func openMigrationFile(path string) (*os.File, error) {
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	// Hold a read-only handle that denies concurrent writers while copying
	// the SQLite database. Existing writers cause a sharing violation.
	handle, err := syscall.CreateFile(name, syscall.GENERIC_READ, syscall.FILE_SHARE_READ, nil, syscall.OPEN_EXISTING, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(handle), path), nil
}

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
