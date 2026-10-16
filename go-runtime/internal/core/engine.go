package core

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
	"unicode"
)

type device struct {
	serverID string
	ac       bool
	public   Object
}
type Engine struct {
	waiting                                                    atomic.Int32
	mu                                                         sync.Mutex
	gate                                                       chan struct{}
	generation                                                 atomic.Uint64
	deviceGeneration                                           uint64
	token, deviceID, source, validation, persistence, revision string
	smsMobile, captchaMobile, captchaToken                     string
	devices                                                    map[string]device
	ids                                                        map[string]string
	store                                                      *Store
	http                                                       *http.Client
	endpoint                                                   string
	shared                                                     bool
}

func NewEngine(store *Store) *Engine {
	e := &Engine{gate: make(chan struct{}, 1), deviceID: ID(), source: "none", validation: "not_authenticated", persistence: "disabled", devices: map[string]device{}, ids: map[string]string{}, store: store, http: newHTTP(), endpoint: BaseURL}
	if store != nil {
		e.persistence = "not_saved"
		rev, s, err := store.Load()
		e.revision = rev
		e.shared = err == nil
		if err != nil {
			e.persistence = safeCode(err)
		} else if s != nil {
			e.token = s.Token
			e.deviceID = s.DeviceID
			e.source = "restored"
			e.validation = "unvalidated"
			e.persistence = "saved"
			e.shared = true
		}
	}
	return e
}
func safeCode(err error) string {
	if e, ok := err.(*SafeError); ok {
		return e.Code
	}
	return "storage_unavailable"
}
func (e *Engine) refreshSaved() {
	e.mu.Lock()
	defer e.mu.Unlock()
	if !e.shared || e.store == nil {
		return
	}
	revision, err := e.store.Revision()
	if err == nil && revision == e.revision {
		return
	}
	var saved *SavedSession
	if err == nil {
		revision, saved, err = e.store.Load()
	}
	e.generation.Add(1)
	e.clear()
	if err != nil {
		e.revision = ""
		e.persistence = safeCode(err)
		return
	}
	e.revision = revision
	e.persistence = "not_saved"
	if saved != nil {
		e.token = saved.Token
		e.deviceID = saved.DeviceID
		e.source = "restored"
		e.validation = "unvalidated"
		e.persistence = "saved"
	}
}
func (e *Engine) Status() Object {
	e.refreshSaved()
	e.mu.Lock()
	defer e.mu.Unlock()
	return Object{"authenticated": e.token != "", "session_source": e.source, "validation_status": e.validation, "persistence_status": e.persistence}
}
func (e *Engine) enter(ctx context.Context) (func(), error) {
	if e.waiting.Add(1) > 16 {
		e.waiting.Add(-1)
		return nil, Err("service_busy")
	}
	defer e.waiting.Add(-1)
	timer := time.NewTimer(5 * time.Second)
	defer timer.Stop()
	select {
	case e.gate <- struct{}{}:
		if e.deviceGeneration != e.generation.Load() {
			e.devices = map[string]device{}
			e.ids = map[string]string{}
			e.deviceGeneration = e.generation.Load()
		}
		return func() { <-e.gate }, nil
	case <-ctx.Done():
		return nil, Err("request_cancelled")
	case <-timer.C:
		return nil, Err("service_busy")
	}
}
func (e *Engine) clear() {
	e.token = ""
	e.source = "none"
	e.validation = "not_authenticated"
	e.smsMobile = ""
	e.captchaMobile = ""
	e.captchaToken = ""
}
func (e *Engine) Logout() (Object, error) {
	e.generation.Add(1)
	e.mu.Lock()
	defer e.mu.Unlock()
	e.clear()
	if e.store != nil && e.shared {
		if err := e.store.Forget(""); err != nil {
			e.persistence = safeCode(err)
			return nil, Err("logout_incomplete")
		}
		e.revision = "" // Reload the complete record next time; never consume a concurrent login revision alone.
		e.persistence = "not_saved"
	}
	return Object{"status": "logged_out", "authenticated": false}, nil
}
func (e *Engine) expire() {
	e.generation.Add(1)
	e.mu.Lock()
	defer e.mu.Unlock()
	e.clear()
	if e.store != nil && e.shared {
		if err := e.store.Forget(e.revision); err != nil {
			e.persistence = safeCode(err)
		} else {
			e.persistence = "not_saved"
		}
	}
}
func (e *Engine) Discard() { e.generation.Add(1); e.mu.Lock(); e.clear(); e.mu.Unlock() }
func (e *Engine) Finish(remember bool) (Object, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.token == "" {
		return nil, Err("not_authenticated")
	}
	e.shared = false
	if remember && e.store != nil {
		rev, err := e.store.Save(SavedSession{e.token, e.deviceID}, e.revision)
		if err != nil {
			e.persistence = safeCode(err)
			if e.persistence == "session_changed" {
				e.clear()
				return nil, Err("session_changed")
			}
		} else {
			e.revision = rev
			e.persistence = "saved"
			e.shared = true
		}
	} else if e.store != nil {
		e.persistence = "not_saved"
	}
	return Object{"persistence_status": e.persistence}, nil
}
func (e *Engine) stop(c string) error {
	codes := map[string]string{"1105": "registration_required", "1405": "account_recovery_required", "1407": "account_recovery_required", "1129": "rate_limited", "40429": "rate_limited"}
	if v := codes[c]; v != "" {
		return Err(v)
	}
	return nil
}

var mobileRE = regexp.MustCompile(`^1[3-9][0-9]{9}$`)

func (e *Engine) SMS(ctx context.Context, mobile, captcha string) (Object, error) {
	e.refreshSaved()
	done, err := e.enter(ctx)
	if err != nil {
		return nil, err
	}
	defer done()
	g := e.generation.Load()
	if !mobileRE.MatchString(mobile) {
		return nil, Err("invalid_mobile")
	}
	e.mu.Lock()
	if e.token != "" {
		e.mu.Unlock()
		return Object{"status": "authenticated"}, nil
	}
	data := Object{"deviceId": e.deviceID, "imgCode": ""}
	if captcha != "" {
		if e.captchaMobile != mobile || e.captchaToken == "" {
			e.mu.Unlock()
			return nil, Err("captcha_unavailable")
		}
		data["imgCode"] = captcha
		data["randomToken"] = e.captchaToken
	}
	e.smsMobile = ""
	e.captchaMobile = ""
	e.captchaToken = ""
	e.mu.Unlock()
	r, err := e.request(ctx, SMS, Object{"data": data, "iotData": Object{"type": 9, "mobile": mobile, "iotAppId": "900"}}, false, false, g)
	if err != nil {
		return nil, err
	}
	if err = e.stop(code(r["code"])); err != nil {
		return nil, err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.generation.Load() != g {
		return nil, Err("session_changed")
	}
	if code(r["code"]) == "65011" {
		p := obj(r["data"])
		image, token := text(p["imgCode"]), text(p["randomToken"])
		if token == "" || len(token) > 4096 || len(image) > 1500000 {
			return nil, Err("malformed_response")
		}
		if strings.HasPrefix(image, "data:") {
			parts := strings.SplitN(image, ",", 2)
			if len(parts) != 2 {
				return nil, Err("malformed_response")
			}
			image = parts[1]
		}
		b, err := base64.StdEncoding.DecodeString(strings.Join(strings.Fields(image), ""))
		if err != nil || len(b) > 512*1024 {
			return nil, Err("malformed_response")
		}
		mime := ""
		switch {
		case strings.HasPrefix(string(b), "\x89PNG\r\n\x1a\n"):
			mime = "png"
		case strings.HasPrefix(string(b), "\xff\xd8\xff"):
			mime = "jpeg"
		case strings.HasPrefix(string(b), "GIF87a") || strings.HasPrefix(string(b), "GIF89a"):
			mime = "gif"
		case len(b) > 12 && string(b[:4]) == "RIFF" && string(b[8:12]) == "WEBP":
			mime = "webp"
		}
		if mime == "" {
			return nil, Err("malformed_response")
		}
		e.captchaMobile = mobile
		e.captchaToken = token
		return Object{"status": "captcha_required", "captcha_data_url": "data:image/" + mime + ";base64," + base64.StdEncoding.EncodeToString(b)}, nil
	}
	if !good(code(r["code"])) {
		return nil, Err("server_rejected")
	}
	e.smsMobile = mobile
	return Object{"status": "sms_sent"}, nil
}
func (e *Engine) Verify(ctx context.Context, mobile, otp string) error {
	e.refreshSaved()
	done, err := e.enter(ctx)
	if err != nil {
		return err
	}
	defer done()
	g := e.generation.Load()
	e.mu.Lock()
	if e.smsMobile != mobile {
		e.mu.Unlock()
		return Err("sms_not_requested")
	}
	id := e.deviceID
	e.mu.Unlock()
	if !regexp.MustCompile(`^[0-9]{6}$`).MatchString(otp) {
		return Err("invalid_sms_code")
	}
	r, err := e.request(ctx, Login, Object{"data": Object{"appKey": "46579c15", "appVersion": Version, "deviceId": id, "deviceName": "Meiju MCP Go", "osVersion": "Go", "platform": 2}, "iotData": Object{"mobile": mobile, "smsCode": otp, "iotAppId": "900", "appVersion": Version, "deviceId": id, "loginType": 0}}, false, false, g)
	if err != nil {
		return err
	}
	if err = e.stop(code(r["code"])); err != nil {
		return err
	}
	p, err := e.payload(r)
	if err != nil {
		return err
	}
	token := text(obj(p["mdata"])["accessToken"])
	if !validToken(token) {
		return Err("malformed_response")
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.generation.Load() != g {
		return Err("session_changed")
	}
	e.token = token
	e.source = "memory"
	e.validation = "validated"
	e.smsMobile = ""
	e.captchaToken = ""
	return nil
}
func identifier(v any) (string, error) {
	var s string
	switch x := v.(type) {
	case string:
		s = x
	case json.Number:
		if strings.ContainsAny(x.String(), ".eE") {
			return "", Err("malformed_response")
		}
		s = x.String()
	default:
		return "", Err("malformed_response")
	}
	if len(s) == 0 || len(s) > 128 {
		return "", Err("malformed_response")
	}
	for _, r := range s {
		if r < 33 {
			return "", Err("malformed_response")
		}
	}
	return s, nil
}
func display(v any) any {
	s, ok := v.(string)
	if !ok {
		return nil
	}
	s = strings.TrimSpace(s)
	rs := []rune{}
	for _, r := range s {
		if unicode.IsPrint(r) {
			rs = append(rs, r)
		}
	}
	if len(rs) > 128 {
		rs = rs[:128]
	}
	if len(rs) == 0 {
		return nil
	}
	return string(rs)
}
func (e *Engine) refresh(ctx context.Context, g uint64) (Object, error) {
	e.devices = map[string]device{}
	p, err := e.read(ctx, Homes, Object{"devicePermissions": true}, g)
	if err != nil {
		return nil, err
	}
	homes, ok := array(p["homeList"])
	if !ok {
		return nil, Err("malformed_response")
	}
	next := map[string]device{}
	public := []any{}
	seenHomes := map[string]bool{}
	seenDevices := map[string]bool{}
	for _, h := range homes {
		home := obj(h)
		hid, err := identifier(home["homegroupId"])
		if err != nil || seenHomes[hid] {
			return nil, Err("malformed_response")
		}
		seenHomes[hid] = true
		p, err := e.read(ctx, Devices, Object{"homegroupId": hid}, g)
		if err != nil {
			return nil, err
		}
		returned, ok := array(p["homeList"])
		if !ok {
			return nil, Err("malformed_response")
		}
		var match Object
		matches := 0
		for _, v := range returned {
			m := obj(v)
			id, er := identifier(m["homegroupId"])
			if er != nil {
				return nil, er
			}
			if id == hid {
				match = m
				matches++
			}
		}
		rooms, ok := array(match["roomList"])
		if matches != 1 || !ok {
			return nil, Err("malformed_response")
		}
		for _, v := range rooms {
			room := obj(v)
			if room == nil {
				return nil, Err("malformed_response")
			}
			apps := []any{}
			if room["applianceList"] != nil {
				apps, ok = array(room["applianceList"])
				if !ok {
					return nil, Err("malformed_response")
				}
			}
			for _, v := range apps {
				a := obj(v)
				sid, er := identifier(a["applianceCode"])
				if er != nil || seenDevices[sid] {
					return nil, Err("malformed_response")
				}
				seenDevices[sid] = true
				opaque := e.ids[sid]
				if opaque == "" {
					opaque = "dev_" + ID()
					e.ids[sid] = opaque
				}
				ac := IsAC(a["type"])
				var typ, profile any = display(a["type"]), nil
				if ac {
					typ = "0xAC"
					profile = "generic_ac_lua_v1"
				}
				name := display(a["name"])
				if name == nil {
					name = "Unnamed device"
				}
				sn := code(a["sn8"])
				var sn8 any
				if regexp.MustCompile(`^[a-zA-Z0-9]{8}$`).MatchString(sn) {
					sn8 = sn
				}
				var online any
				if x := code(a["onlineStatus"]); x == "1" {
					online = true
				} else if x == "0" {
					online = false
				}
				pub := Object{"device_id": opaque, "name": name, "home_name": display(home["name"]), "room_name": display(room["name"]), "model": display(a["productModel"]), "type": typ, "sn8": sn8, "online": online, "profile": profile}
				next[opaque] = device{sid, ac, pub}
				public = append(public, pub)
			}
		}
	}
	if e.generation.Load() != g {
		return nil, Err("session_changed")
	}
	e.devices = next
	return Object{"devices": public}, nil
}
func (e *Engine) get(id string) (device, error) {
	e.mu.Lock()
	auth := e.token != ""
	e.mu.Unlock()
	if !auth {
		return device{}, Err("not_authenticated")
	}
	d, ok := e.devices[id]
	if !ok {
		return d, Err("device_not_available")
	}
	if !d.ac {
		return d, Err("unsupported_device_type")
	}
	return d, nil
}
func (e *Engine) state(ctx context.Context, id string, g uint64) (Object, error) {
	d, err := e.get(id)
	if err != nil {
		return nil, err
	}
	p, err := e.read(ctx, Status, Object{"applianceCode": d.serverID, "command": Object{"query": Object{}}}, g)
	if err != nil {
		return nil, err
	}
	if len(p) == 0 {
		return nil, Err("empty_status")
	}
	s := ParseState(p)
	s["device_id"] = id
	s["source"] = "cloud"
	s["freshness"] = "unknown"
	s["received_at"] = time.Now().UTC().Format(time.RFC3339Nano)
	s["execution_verified"] = false
	return s, nil
}
func (e *Engine) Call(ctx context.Context, name string, args Object) (Object, error) {
	e.refreshSaved()
	ctx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	if name == "meiju_login_status" {
		return e.Status(), nil
	}
	if name == "meiju_logout" {
		return e.Logout()
	}
	done, err := e.enter(ctx)
	if err != nil {
		return nil, err
	}
	defer done()
	g := e.generation.Load()
	id := text(args["device_id"])
	switch name {
	case "meiju_list_devices":
		return e.refresh(ctx, g)
	case "meiju_get_status":
		return e.state(ctx, id, g)
	case "meiju_get_capabilities":
		s, err := e.state(ctx, id, g)
		if err != nil {
			return nil, err
		}
		caps := Capabilities(s)
		caps["device_id"] = id
		return caps, nil
	case "meiju_control":
		changes, wire, err := Changes(args)
		if err != nil {
			return nil, err
		}
		if _, err = e.get(id); err != nil {
			return nil, err
		}
		if _, err = e.refresh(ctx, g); err != nil {
			return nil, err
		}
		d, err := e.get(id)
		if err != nil {
			return nil, err
		}
		before, err := e.state(ctx, id, g)
		if err != nil {
			return nil, err
		}
		for k := range changes {
			if before[k] == nil {
				return nil, Err("unobserved_field")
			}
		}
		r, err := e.request(ctx, Control, Object{"applianceCode": d.serverID, "command": Object{"control": wire}}, true, true, g)
		if err != nil {
			return nil, err
		}
		c := code(r["code"])
		n, er := strconv.ParseInt(c, 10, 64)
		if er != nil {
			return nil, uncertain("write_uncertain")
		}
		if n != 0 {
			if c == "7400" || c == "40002" {
				e.expire()
				return nil, Err("session_expired")
			}
			return nil, Err("server_rejected")
		}
		if v, exists := r["data"]; exists && v == nil {
			return nil, uncertain("write_uncertain")
		}
		back, err := e.state(ctx, id, g)
		verification := "cloud_match"
		var backErr any
		if err != nil {
			verification = "unavailable"
			if safe, ok := err.(*SafeError); ok {
				backErr = safe
			} else {
				backErr = Err("internal_error")
			}
		} else {
			for k, v := range changes {
				if back[k] == nil {
					verification = "unavailable"
					break
				}
				a, _ := JSON(v)
				b, _ := JSON(back[k])
				if string(a) != string(b) {
					verification = "cloud_differs"
				}
			}
		}
		var readback any
		if back != nil {
			readback = back
		}
		return Object{"device_id": id, "acknowledged": true, "requested": changes, "verification": verification, "readback": readback, "readback_error": backErr, "execution_verified": false, "message": "A cloud ACK and possibly cached readback do not verify physical device execution."}, nil
	}
	return nil, Err("unknown_tool")
}

// NewEngineWithHTTP is a trusted transport injection for offline contract tests.
// The public CLI never accepts an alternate cloud endpoint.
func NewEngineWithHTTP(store *Store, client *http.Client, endpoint string) *Engine {
	e := NewEngine(store)
	e.http = client
	e.endpoint = endpoint
	return e
}
