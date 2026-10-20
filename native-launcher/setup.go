package main

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"html/template"
	"net"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

type wizard struct {
	server                   *http.Server
	host, origin, token, url string
	app                      *application
}

func (a *application) openSetup() (string, error) {
	a.mu.Lock()
	if a.wizard == nil {
		listener, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			a.mu.Unlock()
			return "", err
		}
		var token [32]byte
		if _, err = rand.Read(token[:]); err != nil {
			listener.Close()
			a.mu.Unlock()
			return "", err
		}
		w := &wizard{host: listener.Addr().String(), token: hex.EncodeToString(token[:]), app: a}
		w.origin = "http://" + w.host
		w.url = w.origin + "/" + w.token + "/"
		w.server = &http.Server{Handler: w, ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 20 * time.Second, WriteTimeout: 20 * time.Second}
		a.wizard = w
		go w.server.Serve(listener)
	}
	url := a.wizard.url
	a.mu.Unlock()
	// The page is also returned as a clickable link when browser launch is
	// unavailable. No shell, terminal, or credential is passed to this command.
	if os.Getenv("BYTEPLUS_CREATIVE_NO_BROWSER") != "1" {
		_ = openBrowser(url)
	}
	return url, nil
}

func openBrowser(url string) error {
	var command *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		command = exec.Command("/usr/bin/open", url)
	case "windows":
		command = exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", url)
	default:
		command = exec.Command("xdg-open", url)
	}
	hideWindow(command)
	if err := command.Start(); err != nil {
		return err
	}
	go command.Wait()
	return nil
}

func (w *wizard) ServeHTTP(response http.ResponseWriter, request *http.Request) {
	response.Header().Set("Cache-Control", "no-store")
	// HTML form POSTs use this policy when serializing Origin. no-referrer
	// produces Origin: null and makes our own form fail the check below.
	// same-origin retains the local origin and suppresses cross-origin referrers.
	response.Header().Set("Referrer-Policy", "same-origin")
	response.Header().Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	if request.Host != w.host || request.URL.Path != "/"+w.token+"/" {
		http.NotFound(response, request)
		return
	}
	if request.Method != http.MethodGet && request.Method != http.MethodPost {
		response.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	values, err := w.app.settings()
	if err != nil {
		http.Error(response, "配置文件无法读取。请联系支持人员协助处理。", http.StatusInternalServerError)
		return
	}
	message, problem := "", ""
	if request.Method == http.MethodPost {
		if request.Header.Get("Origin") != w.origin {
			http.Error(response, "请求来源无效，请从插件重新打开配置页面。", http.StatusForbidden)
			return
		}
		request.Body = http.MaxBytesReader(response, request.Body, 32*1024)
		mediaType := strings.Split(request.Header.Get("Content-Type"), ";")[0]
		if mediaType != "application/x-www-form-urlencoded" || request.ParseForm() != nil || subtle.ConstantTimeCompare([]byte(request.PostForm.Get("csrf")), []byte(w.token)) != 1 {
			http.Error(response, "无效的配置请求。", http.StatusBadRequest)
			return
		}
		candidate := make(map[string]string, len(values))
		for key, value := range values {
			candidate[key] = value
		}
		for _, key := range []string{"api_key", "access_key", "secret_key", "session_token"} {
			if value := strings.TrimSpace(request.PostForm.Get(key)); value != "" {
				candidate[key] = value
			}
		}
		if request.PostForm.Get("clear_iam") == "yes" {
			candidate["access_key"], candidate["secret_key"], candidate["session_token"] = "", "", ""
		}
		for _, key := range []string{"tos_bucket", "seed_model", "project"} {
			candidate[key] = strings.TrimSpace(request.PostForm.Get(key))
		}
		if candidate["project"] == "" {
			candidate["project"] = "default"
		}
		switch {
		case candidate["api_key"] == "":
			problem = "请填写 ModelArk API Key。"
		case (candidate["access_key"] == "") != (candidate["secret_key"] == ""):
			problem = "IAM Access Key 与 Secret Key 需要一起填写。"
		case strings.HasPrefix(candidate["access_key"], "AKTP") && candidate["session_token"] == "":
			problem = "临时 IAM 凭据还需要填写 Session Token。"
		default:
			if err = w.app.saveSettings(candidate); err != nil {
				problem = "配置未能保存到本机，请检查文件夹权限。"
			} else {
				values = candidate
				message = "配置已保存在本机。请返回 ChatGPT，让 BytePlus Creative Kit 查询准备状态。"
				w.app.beginPrepare()
			}
		}
	}
	public := map[string]string{"project": values["project"], "tos_bucket": values["tos_bucket"], "seed_model": values["seed_model"]}
	data, _ := resources.ReadFile("setup.html")
	page, err := template.New("setup").Parse(string(data))
	if err != nil {
		http.Error(response, "页面加载失败", 500)
		return
	}
	response.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = page.Execute(response, object{"URL": template.URL(w.url), "CSRF": w.token, "Public": public, "APIConfigured": values["api_key"] != "", "IAMConfigured": values["access_key"] != "", "Message": message, "Problem": problem, "Status": w.app.status()})
}
