package core

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type Object = map[string]any

const BaseURL = "https://mp-prod.smartmidea.net/mas/v5/app/proxy"
const SMS = "/mj/user/getSmsCode"
const Login = "/v6/mj/user/register"
const Homes = "/v2/homegroup/list/get"
const Devices = "/v1/appliance/home/list/get"
const Status = "/mjl/v1/device/status/lua/get"
const Control = "/mjl/v1/device/lua/control"
const Version = "11.7.10"

// Public application protocol identifiers; see repository NOTICE, not user credentials.
func Signature(body []byte, random string) string {
	m := hmac.New(sha256.New, []byte("PROD_VnoClJI9aikS8dyy"))
	m.Write([]byte("prod_secret123@muc"))
	m.Write(body)
	m.Write([]byte(random))
	return hex.EncodeToString(m.Sum(nil))
}
func ID() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		panic("random source unavailable")
	}
	return hex.EncodeToString(b)
}
func JSON(v any) ([]byte, error) {
	var b bytes.Buffer
	e := json.NewEncoder(&b)
	e.SetEscapeHTML(false)
	err := e.Encode(v)
	return bytes.TrimSuffix(b.Bytes(), []byte("\n")), err
}
func Decode(b []byte, v any) error {
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	if err := d.Decode(v); err != nil {
		return err
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return Err("malformed_response")
	}
	return nil
}

type SafeError struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Uncertain bool   `json:"uncertain"`
}

func (e *SafeError) Error() string { return e.Code }
func Err(code string) *SafeError {
	e := &SafeError{Code: code, Message: map[string]string{"not_authenticated": "Sign in through the local login page first.", "session_changed": "The local session changed; start a new request.", "session_expired": "The cloud session expired; sign in locally again.", "invalid_input": "参数不符合工具定义。", "device_not_available": "Select a device from a fresh account device list."}[code]}
	if e.Message == "" {
		e.Message = "操作未完成，请检查服务状态；不会自动重试控制。"
	}
	return e
}
func uncertain(code string) *SafeError { e := Err(code); e.Uncertain = true; return e }
func text(v any) string                { s, _ := v.(string); return s }
func obj(v any) Object                 { m, _ := v.(map[string]any); return m }
func array(v any) ([]any, bool)        { a, ok := v.([]any); return a, ok }
func code(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case json.Number:
		if _, e := x.Int64(); e == nil {
			return x.String()
		}
	}
	return ""
}
func good(c string) bool { return c == "0" || c == "0000" || c == "200" }
func validToken(t string) bool {
	if len(t) == 0 || len(t) > 4096 {
		return false
	}
	for _, c := range t {
		if c < 33 || c > 126 {
			return false
		}
	}
	return true
}
func newHTTP() *http.Client {
	return &http.Client{Timeout: 30 * time.Second, Transport: &http.Transport{Proxy: nil, DisableCompression: true, TLSHandshakeTimeout: 10 * time.Second}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}
func (e *Engine) request(ctx context.Context, alias string, fields Object, auth bool, write bool, g uint64) (Object, error) {
	allowed := map[string]bool{SMS: true, Login: true, Homes: true, Devices: true, Status: true, Control: true}
	if !allowed[alias] {
		return nil, Err("invalid_request")
	}
	stamp := time.Now().Format("20060102150405")
	fields["reqId"] = ID()
	fields["stamp"] = stamp
	if alias == SMS || alias == Login {
		fields["timestamp"] = stamp
		iot := obj(fields["iotData"])
		iot["stamp"] = stamp
		iot["reqId"] = ID()
	}
	raw, err := JSON(fields)
	if err != nil {
		return nil, Err("invalid_request")
	}
	random := strconv.FormatInt(time.Now().UnixMilli(), 10)
	req, err := http.NewRequestWithContext(ctx, "POST", e.endpoint+"?alias="+url.QueryEscape(alias), bytes.NewReader(raw))
	if err != nil {
		return nil, Err("invalid_request")
	}
	for k, v := range map[string]string{"Content-Type": "application/json; charset=utf-8", "secretVersion": "1", "random": random, "sign": Signature(raw, random), "version": Version, "systemVersion": "Go", "platform": "0", "Accept-Encoding": "identity", "terminalId": "900-android", "appId": "900"} {
		req.Header.Set(k, v)
	}
	if auth {
		e.mu.Lock()
		token := e.token
		e.mu.Unlock()
		if !validToken(token) {
			return nil, Err("not_authenticated")
		}
		req.Header.Set("accessToken", token)
	}
	e.refreshSaved()
	if e.generation.Load() != g {
		return nil, Err("session_changed")
	}
	resp, err := e.http.Do(req)
	if err != nil {
		if write {
			return nil, uncertain("write_uncertain")
		}
		return nil, Err("transport_error")
	}
	defer resp.Body.Close()
	fail := func(c string) (Object, error) {
		if write {
			return nil, uncertain(c)
		}
		return nil, Err(c)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fail("http_error")
	}
	if enc := resp.Header.Get("Content-Encoding"); enc != "" && !strings.EqualFold(enc, "identity") {
		return fail("unsupported_encoding")
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, 2*1024*1024+1))
	if err != nil {
		return fail("transport_error")
	}
	if len(b) > 2*1024*1024 {
		return fail("response_too_large")
	}
	e.refreshSaved()
	if e.generation.Load() != g {
		return fail("session_changed")
	}
	var result Object
	if Decode(b, &result) != nil || code(result["code"]) == "" {
		return fail("malformed_response")
	}
	return result, nil
}
func (e *Engine) payload(r Object) (Object, error) {
	c := code(r["code"])
	if !good(c) {
		if c == "7400" || c == "40002" {
			e.expire()
			return nil, Err("session_expired")
		}
		return nil, Err("server_rejected")
	}
	p := obj(r["data"])
	if p == nil {
		return nil, Err("malformed_response")
	}
	return p, nil
}
func (e *Engine) read(ctx context.Context, alias string, fields Object, g uint64) (Object, error) {
	r, err := e.request(ctx, alias, fields, true, false, g)
	if err != nil {
		return nil, err
	}
	p, err := e.payload(r)
	if err == nil {
		e.mu.Lock()
		e.validation = "validated"
		e.mu.Unlock()
	}
	return p, err
}
