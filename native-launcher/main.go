// A dependency-free desktop MCP entry point. Python is prepared in the
// background only after setup, so plugin discovery never waits on downloads.
package main

import (
	"bufio"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
)

const version = "0.2.4"

//go:embed tools.json setup.html
var resources embed.FS

type object = map[string]any

type application struct {
	root, data, environment string
	mu                      sync.Mutex
	preparing               bool
	prepareError            string
	wizard                  *wizard
	worker                  *worker
	workerConfig            [32]byte
}

func newApplication(root, data string) (*application, error) {
	if err := os.MkdirAll(data, 0700); err != nil {
		return nil, err
	}
	// MSIX can redirect AppData writes to the host's private package folder.
	// Pass the opened directory's physical path to uv so its absolute Python
	// junction targets refer to the files that Windows actually created.
	physical, err := physicalDirectory(data)
	if err != nil {
		return nil, err
	}
	data = physical
	// A virtual environment belongs to an installed plugin path. Credentials
	// and import records remain shared across versions outside that path.
	digest := sha256.Sum256([]byte(root + "\x00" + version))
	return &application{root: root, data: data, environment: filepath.Join(data, "runtime", hex.EncodeToString(digest[:8]))}, nil
}

func (a *application) settingsPath() string { return filepath.Join(a.data, "settings.json") }

func (a *application) settings() (map[string]string, error) {
	values := map[string]string{"project": "default", "api_key": "", "access_key": "", "secret_key": "", "session_token": "", "tos_bucket": "", "seed_model": ""}
	data, err := os.ReadFile(a.settingsPath())
	if errors.Is(err, os.ErrNotExist) {
		return values, nil
	}
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(data, &values); err != nil {
		return nil, errors.New("本地配置无法读取，请重新打开配置页面")
	}
	return values, nil
}

func (a *application) saveSettings(values map[string]string) error {
	data, err := json.MarshalIndent(values, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(a.data, ".settings-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if err = f.Chmod(0600); err == nil {
		_, err = f.Write(append(data, '\n'))
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), a.settingsPath())
}

func (a *application) python() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(a.environment, "venv", "Scripts", "python.exe")
	}
	return filepath.Join(a.environment, "venv", "bin", "python")
}

func (a *application) ready() bool {
	_, err := os.Stat(filepath.Join(a.environment, "ready"))
	_, pyErr := os.Stat(a.python())
	return err == nil && pyErr == nil
}

func (a *application) status() object {
	values, err := a.settings()
	if err != nil {
		return object{"status": "error", "message": err.Error()}
	}
	a.mu.Lock()
	preparing, prepareError := a.preparing, a.prepareError
	a.mu.Unlock()
	state := "not_prepared"
	if a.ready() {
		state = "ready"
	} else if preparing {
		state = "preparing"
	} else if prepareError != "" {
		state = "failed"
	}
	home, _ := os.UserHomeDir()
	return object{"status": "ok", "version": version, "generation_configured": values["api_key"] != "", "asset_library_configured": values["access_key"] != "" && values["secret_key"] != "", "local_upload_configured": values["tos_bucket"] != "" && values["access_key"] != "" && values["secret_key"] != "", "seed_text_configured": values["seed_model"] != "", "project": values["project"], "bucket": values["tos_bucket"], "runtime": state, "runtime_error": prepareError, "outputs_folder": filepath.Join(home, "Downloads", "BytePlus Creative Kit"), "message": "若尚未配置，请运行 creative_kit_setup，在本机页面填写凭据。环境准备期间可稍后查询状态；尚未提交任何生成任务。"}
}

func toolResult(value object, failed bool) object {
	data, _ := json.Marshal(value)
	return object{"content": []object{{"type": "text", "text": string(data)}}, "structuredContent": value, "isError": failed}
}

func localTool(name, description string) object {
	return object{"name": name, "description": description, "inputSchema": object{"type": "object", "properties": object{}, "additionalProperties": false}, "outputSchema": object{"type": "object", "additionalProperties": true}, "annotations": object{"readOnlyHint": name == "creative_kit_status", "destructiveHint": false, "openWorldHint": false}}
}

func listedTools() ([]object, error) {
	data, err := resources.ReadFile("tools.json")
	if err != nil {
		return nil, err
	}
	var tools []object
	if err = json.Unmarshal(data, &tools); err != nil {
		return nil, err
	}
	return append([]object{localTool("creative_kit_setup", "打开 BytePlus Creative Kit 的本机配置页面，在浏览器中填写或更换 ModelArk API Key、IAM 凭据及 TOS 存储桶。不要在聊天中索取密钥。保存后自动准备运行环境，无需终端、Python 或 Docker；不会生成或上传媒体。"), localTool("creative_kit_status", "查询本机配置是否齐全、运行环境准备状态和结果目录。只返回状态，不返回任何密钥，也不调用 BytePlus。")}, tools...), nil
}

func (a *application) callTool(name string, args json.RawMessage) (object, error) {
	switch name {
	case "creative_kit_status":
		return toolResult(a.status(), false), nil
	case "creative_kit_setup":
		url, err := a.openSetup()
		if err != nil {
			return nil, err
		}
		return toolResult(object{"status": "setup_opened", "setup_url": url, "message": "请在已打开的本机页面填写凭据并保存；不要把密钥发送到聊天中。保存后自动准备运行环境，再查询 creative_kit_status。此链接仅用于本机配置，不要分享。"}, false), nil
	}
	tools, _ := listedTools()
	found := false
	for _, t := range tools {
		if t["name"] == name {
			found = true
			break
		}
	}
	if !found {
		return nil, fmt.Errorf("unknown tool: %s", name)
	}
	values, err := a.settings()
	if err != nil {
		return nil, err
	}
	if values["api_key"] == "" {
		return toolResult(object{"status": "setup_required", "message": "请先运行 creative_kit_setup，在本机页面保存 BytePlus 配置。不要在聊天中填写密钥。未提交任何云端请求。"}, false), nil
	}
	if name == "seed_text" && values["seed_model"] == "" {
		return toolResult(object{"status": "setup_required", "message": "尚未配置可选的 Seed 文本模型。请打开 creative_kit_setup 填写模型或 Endpoint ID。"}, false), nil
	}
	if !a.ready() {
		a.beginPrepare()
		return toolResult(object{"status": "preparing", "message": "正在自动准备运行环境，请稍后查询 creative_kit_status；就绪后再执行原请求。此次尚未提交生成或上传任务。", "runtime": a.status()}, false), nil
	}
	encoded, _ := json.Marshal(values)
	fingerprint := sha256.Sum256(encoded)
	if a.worker != nil && fingerprint != a.workerConfig {
		a.worker.close()
		a.worker = nil
	}
	if a.worker == nil {
		a.worker, err = startWorker(a)
		if err != nil {
			return nil, errors.New("无法启动本机工具，请重新打开配置页面；如仍失败，请查看本机运行日志")
		}
		a.workerConfig = fingerprint
	}
	result, err := a.worker.call(name, args)
	if err != nil {
		a.worker.close()
		a.worker = nil
		// Never replay a tool call after a lost response: it may already have
		// created an asset or submitted a paid generation.
		return toolResult(object{"status": "submission_unresolved", "message": "工具连接中断，远端请求可能已提交。不要自动重复上传或生成；请使用已有任务/操作 ID 或查询列表核对结果。"}, true), nil
	}
	return result, nil
}

func serve(a *application, input io.Reader, output io.Writer) error {
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 65536), 16*1024*1024)
	encoder := json.NewEncoder(output)
	for scanner.Scan() {
		var request struct {
			ID     json.RawMessage `json:"id"`
			Method string          `json:"method"`
			Params json.RawMessage `json:"params"`
		}
		if json.Unmarshal(scanner.Bytes(), &request) != nil {
			continue
		}
		if len(request.ID) == 0 {
			continue
		}
		response := object{"jsonrpc": "2.0", "id": request.ID}
		var result any
		var err error
		switch request.Method {
		case "initialize":
			var p struct {
				ProtocolVersion string `json:"protocolVersion"`
			}
			_ = json.Unmarshal(request.Params, &p)
			v := p.ProtocolVersion
			if v != "2024-11-05" && v != "2025-03-26" && v != "2025-06-18" && v != "2025-11-25" {
				v = "2025-11-25"
			}
			result = object{"protocolVersion": v, "capabilities": object{"tools": object{}}, "serverInfo": object{"name": "byteplus-creative-kit", "version": version}, "instructions": "Use creative_kit_setup for first-time setup; credentials must be entered in the local browser form, never chat. No terminal is needed. If a tool returns preparing, no cloud request was submitted: poll creative_kit_status until runtime=ready before retrying. For actual uploads/generation, retain IDs and reconcile unknown outcomes before submitting again. Use Seedream for images, Seedance for video, and seedance_library_* for persistent image/video assets. Wait for Active. Use seed_media_download to save completed outputs. Only delete explicitly requested assets. Real-person verification is console-based."}
		case "ping":
			result = object{}
		case "tools/list":
			var tools []object
			tools, err = listedTools()
			result = object{"tools": tools}
		case "tools/call":
			var p struct {
				Name      string          `json:"name"`
				Arguments json.RawMessage `json:"arguments"`
			}
			if err = json.Unmarshal(request.Params, &p); err == nil {
				result, err = a.callTool(p.Name, p.Arguments)
			}
		case "resources/list":
			result = object{"resources": []any{}}
		case "prompts/list":
			result = object{"prompts": []any{}}
		default:
			err = errors.New("method not found")
		}
		if err != nil {
			response["error"] = object{"code": -32603, "message": err.Error()}
		} else {
			response["result"] = result
		}
		if err = encoder.Encode(response); err != nil {
			return err
		}
	}
	return scanner.Err()
}

func main() {
	executable, err := os.Executable()
	if err != nil {
		os.Exit(1)
	}
	root := filepath.Dir(filepath.Dir(executable))
	data := os.Getenv("BYTEPLUS_CREATIVE_DATA_DIR")
	if data == "" {
		base, err := os.UserConfigDir()
		if err != nil {
			os.Exit(1)
		}
		data = filepath.Join(base, "BytePlusCreativeKit")
	}
	a, err := newApplication(root, data)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Cannot initialize BytePlus Creative Kit's local data folder.")
		os.Exit(1)
	}
	defer func() {
		if a.worker != nil {
			a.worker.close()
		}
		if a.wizard != nil {
			a.wizard.server.Close()
		}
	}()
	if len(os.Args) > 1 && strings.TrimSpace(os.Args[1]) == "--version" {
		fmt.Println(version)
		return
	}
	if err = serve(a, os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "BytePlus Creative Kit connection closed.")
	}
}
