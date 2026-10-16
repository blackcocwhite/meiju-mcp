package service

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	assets "github.com/blackcocwhite/meiju-mcp/go-runtime"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
	"io"
	"net"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"
)

type Portal struct {
	mu                                    sync.Mutex
	engine                                *core.Engine
	server                                *http.Server
	origin, secret, mobile, captchaMobile string
	expires, cooldown                     time.Time
	attempts                              int
}

func NewPortal(e *core.Engine) *Portal { return &Portal{engine: e} }
func (p *Portal) Start() (core.Object, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.engine.Status()["authenticated"] == true {
		p.secret = ""
		return core.Object{"status": "authenticated"}, nil
	}
	if p.server == nil {
		l, e := net.Listen("tcp4", "127.0.0.1:0")
		if e != nil {
			return nil, core.Err("service_unavailable")
		}
		p.origin = "http://" + l.Addr().String()
		p.server = &http.Server{Handler: http.HandlerFunc(p.serve), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 75 * time.Second, MaxHeaderBytes: 16384}
		go p.server.Serve(l)
	}
	if p.secret == "" || time.Now().After(p.expires) {
		p.secret = core.ID() + core.ID()
		p.expires = time.Now().Add(10 * time.Minute)
		p.mobile = ""
		p.captchaMobile = ""
		p.attempts = 0
	}
	return core.Object{"status": "login_required", "login_url": p.origin + "/#flow=" + p.secret, "expires_in": int(time.Until(p.expires).Seconds())}, nil
}
func (p *Portal) Invalidate() { p.mu.Lock(); p.secret = ""; p.mu.Unlock() }
func (p *Portal) Close() {
	p.mu.Lock()
	p.secret = ""
	s := p.server
	p.mu.Unlock()
	if s != nil {
		_ = s.Close()
	}
}
func reply(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func failure(w http.ResponseWriter, status int, c string) {
	reply(w, status, core.Object{"status": "error", "code": c, "message": "操作未完成，请检查登录状态后重试。"})
}
func errorCode(err error) string {
	if e, ok := err.(*core.SafeError); ok {
		return e.Code
	}
	return "service_unavailable"
}
func (p *Portal) serve(w http.ResponseWriter, r *http.Request) {
	for k, v := range map[string]string{"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Cross-Origin-Resource-Policy": "same-origin", "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"} {
		w.Header().Set(k, v)
	}
	if r.Host != strings.TrimPrefix(p.origin, "http://") {
		failure(w, 403, "invalid_host")
		return
	}
	origins := r.Header.Values("Origin")
	if len(origins) > 1 || (len(origins) == 1 && origins[0] != p.origin) {
		failure(w, 403, "invalid_origin")
		return
	}
	site := r.Header.Get("Sec-Fetch-Site")
	navigation := r.Method == "GET" && r.URL.Path == "/" && r.Header.Get("Sec-Fetch-Mode") == "navigate" && r.Header.Get("Sec-Fetch-Dest") == "document" && len(origins) == 0
	if (site == "cross-site" || site == "same-site") && !navigation {
		failure(w, 403, "invalid_origin")
		return
	}
	if r.Method == "GET" {
		paths := map[string]string{"/": "index.html", "/login.js": "login.js", "/login.css": "login.css"}
		name, ok := paths[r.URL.Path]
		if !ok {
			http.NotFound(w, r)
			return
		}
		b, _ := assets.Files.ReadFile("web/" + name)
		types := map[string]string{"index.html": "text/html; charset=utf-8", "login.js": "text/javascript; charset=utf-8", "login.css": "text/css; charset=utf-8"}
		w.Header().Set("Content-Type", types[name])
		w.Write(b)
		return
	}
	if r.Method != "POST" || (r.URL.Path != "/api/sms" && r.URL.Path != "/api/login") {
		failure(w, 405, "invalid_request")
		return
	}
	if len(origins) != 1 {
		failure(w, 403, "invalid_origin")
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	authorized := func() bool {
		if p.secret == "" || time.Now().After(p.expires) {
			p.secret = ""
			failure(w, 410, "flow_expired")
			return false
		}
		flows := r.Header.Values("X-Meiju-Flow")
		if len(flows) != 1 || subtle.ConstantTimeCompare([]byte(flows[0]), []byte(p.secret)) != 1 {
			failure(w, 403, "invalid_flow")
			return false
		}
		if p.engine.Status()["authenticated"] == true {
			p.secret = ""
			failure(w, 409, "already_authenticated")
			return false
		}
		return true
	}
	if !authorized() {
		return
	}
	if strings.Split(r.Header.Get("Content-Type"), ";")[0] != "application/json" {
		failure(w, 415, "invalid_input")
		return
	}
	b, err := io.ReadAll(io.LimitReader(r.Body, 8193))
	if err != nil || len(b) > 8192 {
		failure(w, 413, "invalid_input")
		return
	}
	var body core.Object
	if core.Decode(b, &body) != nil || body == nil {
		failure(w, 400, "invalid_input")
		return
	}
	for k, v := range body {
		allowed := k == "mobile" || (r.URL.Path == "/api/sms" && k == "captcha") || (r.URL.Path == "/api/login" && (k == "code" || k == "remember"))
		_, s := v.(string)
		_, bo := v.(bool)
		if !allowed || (k == "remember" && !bo) || (k != "remember" && !s) {
			failure(w, 400, "invalid_input")
			return
		}
	}
	if !authorized() {
		return
	}
	mobile, _ := body["mobile"].(string)
	if !regexp.MustCompile(`^1[3-9][0-9]{9}$`).MatchString(mobile) {
		failure(w, 400, "invalid_input")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	if r.URL.Path == "/api/sms" {
		captcha, _ := body["captcha"].(string)
		follow := captcha != "" && p.captchaMobile == mobile && p.attempts < 3
		if captcha != "" && (!follow || !regexp.MustCompile(`^[A-Za-z0-9]{1,16}$`).MatchString(captcha)) {
			failure(w, 400, "captcha_expired")
			return
		}
		if time.Now().Before(p.cooldown) && !follow {
			reply(w, 429, core.Object{"status": "error", "code": "sms_cooldown", "message": "请稍后再发送验证码。", "retry_after": int(time.Until(p.cooldown).Seconds()) + 1})
			return
		}
		if follow {
			p.attempts++
		} else {
			p.cooldown = time.Now().Add(time.Minute)
			p.mobile = ""
			p.captchaMobile = ""
			p.attempts = 0
		}
		out, err := p.engine.SMS(ctx, mobile, captcha)
		if err != nil {
			p.captchaMobile = ""
			reply(w, 503, core.Object{"status": "error", "code": errorCode(err), "message": "暂时无法发送验证码。", "reset_captcha": true, "retry_after": 60})
			return
		}
		if time.Now().After(p.expires) {
			failure(w, 410, "flow_expired")
			return
		}
		if out["status"] == "captcha_required" {
			p.captchaMobile = mobile
		} else {
			p.mobile = mobile
			p.captchaMobile = ""
			p.cooldown = time.Now().Add(time.Minute)
			out["retry_after"] = 60
		}
		reply(w, 200, out)
		return
	}
	otp, _ := body["code"].(string)
	if !regexp.MustCompile(`^[0-9]{6}$`).MatchString(otp) {
		failure(w, 400, "invalid_input")
		return
	}
	if p.mobile != mobile {
		failure(w, 400, "sms_required")
		return
	}
	if err = p.engine.Verify(ctx, mobile, otp); err != nil {
		failure(w, 400, errorCode(err))
		return
	}
	if time.Now().After(p.expires) {
		p.engine.Discard()
		p.secret = ""
		failure(w, 410, "flow_expired")
		return
	}
	remember, _ := body["remember"].(bool)
	saved, err := p.engine.Finish(remember)
	if err != nil {
		failure(w, 400, errorCode(err))
		return
	}
	p.secret = ""
	saved["status"] = "authenticated"
	saved["message"] = "美居登录成功，可以关闭此页面。"
	if remember {
		saved["message"] = "本次已登录，但未能安全保存；重启后需要重新登录。"
		if saved["persistence_status"] == "saved" {
			saved["message"] = "美居登录成功，已安全记住这台电脑。"
		}
	}
	reply(w, 200, saved)
}
