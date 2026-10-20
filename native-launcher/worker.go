package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

type worker struct {
	command *exec.Cmd
	input   io.WriteCloser
	output  *bufio.Scanner
	next    int
	log     *os.File
}

func startWorker(a *application) (*worker, error) {
	command := exec.Command(a.python(), "-m", "byteplus_creative.plugin_server")
	home, _ := os.UserHomeDir()
	command.Dir = a.root
	command.Env = append(os.Environ(), "BYTEPLUS_CREATIVE_DATA_DIR="+a.data, "BYTEPLUS_CREATIVE_OUTPUT_DIR="+filepath.Join(home, "Downloads", "BytePlus Creative Kit"), "PYTHONUNBUFFERED=1", "PYTHON_DOTENV_DISABLED=1")
	hideWindow(command)
	input, err := command.StdinPipe()
	if err != nil {
		return nil, err
	}
	output, err := command.StdoutPipe()
	if err != nil {
		input.Close()
		return nil, err
	}
	log, err := os.OpenFile(filepath.Join(a.data, "tools.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		input.Close()
		return nil, err
	}
	command.Stderr = log
	if err = command.Start(); err != nil {
		input.Close()
		log.Close()
		return nil, err
	}
	scanner := bufio.NewScanner(output)
	scanner.Buffer(make([]byte, 65536), 16*1024*1024)
	w := &worker{command: command, input: input, output: scanner, log: log}
	_, err = w.request("initialize", object{"protocolVersion": "2025-11-25", "capabilities": object{}, "clientInfo": object{"name": "byteplus-creative-desktop", "version": version}})
	if err != nil {
		w.close()
		return nil, err
	}
	if err = json.NewEncoder(input).Encode(object{"jsonrpc": "2.0", "method": "notifications/initialized"}); err != nil {
		w.close()
		return nil, err
	}
	return w, nil
}

func (w *worker) request(method string, params any) (object, error) {
	w.next++
	if err := json.NewEncoder(w.input).Encode(object{"jsonrpc": "2.0", "id": w.next, "method": method, "params": params}); err != nil {
		return nil, err
	}
	for w.output.Scan() {
		var response struct {
			ID     int    `json:"id"`
			Result object `json:"result"`
			Error  any    `json:"error"`
		}
		if json.Unmarshal(w.output.Bytes(), &response) != nil {
			return nil, errors.New("invalid worker response")
		}
		if response.ID != w.next {
			continue
		}
		if response.Error != nil {
			return nil, errors.New("worker returned an RPC error")
		}
		return response.Result, nil
	}
	return nil, errors.New("worker response ended")
}

func (w *worker) call(name string, args json.RawMessage) (object, error) {
	if len(args) == 0 {
		args = json.RawMessage("{}")
	}
	return w.request("tools/call", object{"name": name, "arguments": args})
}

func (w *worker) close() {
	_ = w.input.Close()
	done := make(chan struct{})
	go func() { _ = w.command.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		_ = w.command.Process.Kill()
		<-done
	}
	_ = w.log.Close()
}
