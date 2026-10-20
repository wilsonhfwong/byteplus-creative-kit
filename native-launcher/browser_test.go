package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

// An external real-browser driver opens this fixture and submits the actual
// setup form. The browser must generate Origin itself; injecting it would miss
// the interaction between Referrer-Policy and HTML form submission.
func TestBrowserSetupForm(t *testing.T) {
	urlFile := os.Getenv("CREATIVE_KIT_BROWSER_URL_FILE")
	if urlFile == "" {
		t.Skip("run with the real-browser setup regression driver")
	}
	a := testApplication(t)
	a.preparing = true // no runtime downloads or BytePlus requests in this fixture
	w := &wizard{app: a, token: "synthetic-browser-test-token"}
	type submission struct {
		code   int
		origin string
	}
	posted := make(chan submission, 1)
	server := httptest.NewServer(http.HandlerFunc(func(out http.ResponseWriter, request *http.Request) {
		recorder := httptest.NewRecorder()
		w.ServeHTTP(recorder, request)
		for key, values := range recorder.Header() {
			out.Header()[key] = values
		}
		out.WriteHeader(recorder.Code)
		_, _ = io.Copy(out, recorder.Body)
		if request.Method == http.MethodPost {
			posted <- submission{recorder.Code, request.Header.Get("Origin")}
		}
	}))
	defer server.Close()
	w.origin = server.URL
	w.host = strings.TrimPrefix(server.URL, "http://")
	w.url = server.URL + "/" + w.token + "/"
	if err := os.WriteFile(urlFile, []byte(w.url), 0600); err != nil {
		t.Fatal(err)
	}
	select {
	case result := <-posted:
		t.Logf("Browser-generated Origin: %q; HTTP status: %d", result.origin, result.code)
		if result.code != http.StatusOK {
			t.Fatalf("browser form submission rejected: HTTP %d", result.code)
		}
		values, err := a.settings()
		if err != nil || values["api_key"] != "synthetic-browser-api-key" || values["project"] != "browser-regression" {
			t.Fatal("browser form did not save the expected synthetic settings")
		}
		if result.origin != w.origin {
			t.Fatal("browser form did not retain its own loopback origin")
		}
	case <-time.After(2 * time.Minute):
		t.Fatal("timed out waiting for the browser to submit the setup form")
	}
}
