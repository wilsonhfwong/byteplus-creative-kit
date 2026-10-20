package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"runtime"
	"strings"
	"testing"
)

func testApplication(t *testing.T) *application {
	t.Helper()
	a, err := newApplication(t.TempDir(), t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func TestFreshPluginDiscoversWithoutPythonOrCredentials(t *testing.T) {
	a := testApplication(t)
	input := strings.NewReader("{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-11-25\"}}\n{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\"}\n")
	var output bytes.Buffer
	if err := serve(a, input, &output); err != nil {
		t.Fatal(err)
	}
	decoder := json.NewDecoder(&output)
	var first, second object
	if err := decoder.Decode(&first); err != nil {
		t.Fatal(err)
	}
	if err := decoder.Decode(&second); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"creative_kit_setup", "creative_kit_status", "seedance_library_import", "seedance_library_delete_asset", "seedream_generate", "seed_text"} {
		encoded, _ := json.Marshal(second)
		if !bytes.Contains(encoded, []byte(`"name":"`+name+`"`)) {
			t.Fatalf("missing %s", name)
		}
	}
	if a.preparing || a.worker != nil {
		t.Fatal("discovery must not install runtime or launch Python")
	}
}

func TestSettingsStatusNeverReturnsSecretValues(t *testing.T) {
	a := testApplication(t)
	values := map[string]string{"api_key": "secret-api-sentinel", "access_key": "secret-ak-sentinel", "secret_key": "secret-sk-sentinel", "session_token": "secret-session-sentinel", "project": "default", "tos_bucket": "private-bucket"}
	if err := a.saveSettings(values); err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(a.status())
	for _, key := range []string{"api_key", "access_key", "secret_key", "session_token"} {
		if bytes.Contains(encoded, []byte(values[key])) {
			t.Fatalf("status leaked %s", key)
		}
	}
	if runtime.GOOS != "windows" {
		info, _ := os.Stat(a.settingsPath())
		if info.Mode().Perm() != 0600 {
			t.Fatal("configuration is not private")
		}
	}
}

func wizardRequest(t *testing.T, w *wizard, method string, form url.Values, origin string) *httptest.ResponseRecorder {
	t.Helper()
	var body io.Reader
	if form != nil {
		body = strings.NewReader(form.Encode())
	}
	request := httptest.NewRequest(method, w.url, body)
	request.Host = w.host
	if method == http.MethodPost {
		request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
		request.Header.Set("Origin", origin)
	}
	response := httptest.NewRecorder()
	w.ServeHTTP(response, request)
	return response
}

func TestLocalSetupRejectsCrossOriginAndKeepsSecretsOutOfPage(t *testing.T) {
	a := testApplication(t)
	a.preparing = true // isolate the form from runtime downloads
	w := &wizard{app: a, host: "127.0.0.1:12345", origin: "http://127.0.0.1:12345", token: "test-token", url: "http://127.0.0.1:12345/test-token/"}
	form := url.Values{"csrf": {"test-token"}, "api_key": {"secret-api-sentinel"}, "access_key": {"secret-ak-sentinel"}, "secret_key": {"secret-sk-sentinel"}, "project": {"default"}, "tos_bucket": {"private-bucket"}}
	for _, origin := range []string{"https://untrusted.example", "null", "", "http://127.0.0.1:54321"} {
		if r := wizardRequest(t, w, http.MethodPost, form, origin); r.Code != http.StatusForbidden {
			t.Fatalf("untrusted origin %q accepted", origin)
		}
	}
	if _, err := os.Stat(a.settingsPath()); !os.IsNotExist(err) {
		t.Fatal("rejected request wrote settings")
	}
	form.Set("csrf", "wrong-token")
	if r := wizardRequest(t, w, http.MethodPost, form, w.origin); r.Code != http.StatusBadRequest {
		t.Fatal("invalid CSRF token accepted")
	}
	form.Set("csrf", "test-token")
	r := wizardRequest(t, w, http.MethodPost, form, w.origin)
	if r.Code != http.StatusOK {
		t.Fatalf("valid setup failed: %d", r.Code)
	}
	for _, secret := range []string{"secret-api-sentinel", "secret-ak-sentinel", "secret-sk-sentinel"} {
		if strings.Contains(r.Body.String(), secret) {
			t.Fatal("setup echoed secret")
		}
	}
	values, _ := a.settings()
	if values["api_key"] != "secret-api-sentinel" || values["tos_bucket"] != "private-bucket" {
		t.Fatal("configuration not saved")
	}
	if r.Header().Get("Cache-Control") != "no-store" || !strings.Contains(r.Header().Get("Content-Security-Policy"), "frame-ancestors 'none'") {
		t.Fatal("missing page protections")
	}
	if r.Header().Get("Referrer-Policy") != "same-origin" {
		t.Fatal("setup policy must preserve the Origin of its own browser form POST")
	}
	blank := url.Values{"csrf": {"test-token"}, "api_key": {""}, "project": {"new-project"}}
	r = wizardRequest(t, w, http.MethodPost, blank, w.origin)
	values, _ = a.settings()
	if values["api_key"] != "secret-api-sentinel" || values["project"] != "new-project" {
		t.Fatal("blank key did not preserve saved credential")
	}
}

func TestLocalSetupRejectsWrongHost(t *testing.T) {
	a := testApplication(t)
	w := &wizard{app: a, host: "127.0.0.1:12345", token: "test-token"}
	r := httptest.NewRequest(http.MethodGet, "http://rebinding.example:12345/test-token/", nil)
	response := httptest.NewRecorder()
	w.ServeHTTP(response, r)
	if response.Code != http.StatusNotFound {
		t.Fatal("invalid Host header accepted")
	}
}

func TestPreparingNeverStartsCloudWorker(t *testing.T) {
	a := testApplication(t)
	a.preparing = true
	if err := a.saveSettings(map[string]string{"api_key": "dummy"}); err != nil {
		t.Fatal(err)
	}
	value, err := a.callTool("seedream_generate", json.RawMessage(`{"prompt":"test"}`))
	if err != nil {
		t.Fatal(err)
	}
	encoded, _ := json.Marshal(value)
	if !bytes.Contains(encoded, []byte(`"status":"preparing"`)) || a.worker != nil {
		t.Fatal("unprepared runtime submitted a tool call")
	}
}

func TestUnknownToolCannotReachWorker(t *testing.T) {
	a := testApplication(t)
	if _, err := a.callTool("unexpected_tool", json.RawMessage(`{}`)); err == nil || a.worker != nil {
		t.Fatal("unknown tool was forwarded")
	}
}
