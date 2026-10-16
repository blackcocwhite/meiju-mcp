//go:build linux

package vaultworker

import "github.com/godbus/dbus"

const busName = "org.freedesktop.secrets"

type nativeBackend struct{}
type secret struct {
	Session     dbus.ObjectPath
	Parameters  []byte
	Value       []byte
	ContentType string
}

func search(key string) (*dbus.Conn, dbus.ObjectPath, string) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return nil, "", "storage_unavailable"
	}
	service := conn.Object(busName, "/org/freedesktop/secrets")
	var unlocked, locked []dbus.ObjectPath
	err = service.Call("org.freedesktop.Secret.Service.SearchItems", 0, map[string]string{"service": "meiju-mcp.vault.v1", "account": key}).Store(&unlocked, &locked)
	if err != nil {
		return nil, "", "storage_unavailable"
	}
	if len(unlocked)+len(locked) > 1 {
		return nil, "", "storage_corrupt"
	}
	if len(locked) > 0 {
		return nil, "", "storage_authorization_required"
	}
	if len(unlocked) == 0 {
		return conn, "", ""
	}
	return conn, unlocked[0], ""
}
func session(conn *dbus.Conn) (dbus.ObjectPath, string) {
	var output dbus.Variant
	var path dbus.ObjectPath
	if conn.Object(busName, "/org/freedesktop/secrets").Call("org.freedesktop.Secret.Service.OpenSession", 0, "plain", dbus.MakeVariant("")).Store(&output, &path) != nil {
		return "", "storage_unavailable"
	}
	return path, ""
}
func (nativeBackend) Get(key string) ([]byte, bool, string) {
	conn, item, code := search(key)
	if code != "" || item == "" {
		return nil, false, code
	}
	s, code := session(conn)
	if code != "" {
		return nil, false, code
	}
	defer conn.Object(busName, s).Call("org.freedesktop.Secret.Session.Close", 0)
	var value secret
	if conn.Object(busName, item).Call("org.freedesktop.Secret.Item.GetSecret", 0, s).Store(&value) != nil {
		return nil, false, "storage_unavailable"
	}
	return value.Value, true, ""
}
func (nativeBackend) Create(key string, value []byte) string {
	conn, item, code := search(key)
	if code != "" {
		return code
	}
	if item != "" {
		return "storage_item_exists"
	}
	service := conn.Object(busName, "/org/freedesktop/secrets")
	var collection dbus.ObjectPath
	if service.Call("org.freedesktop.Secret.Service.ReadAlias", 0, "default").Store(&collection) != nil {
		return "storage_unavailable"
	}
	if collection == "/" || collection == "" {
		return "storage_authorization_required"
	}
	object := conn.Object(busName, collection)
	locked, err := object.GetProperty("org.freedesktop.Secret.Collection.Locked")
	if err != nil {
		return "storage_unavailable"
	}
	if isLocked, ok := locked.Value().(bool); !ok || isLocked {
		return "storage_authorization_required"
	}
	s, code := session(conn)
	if code != "" {
		return code
	}
	defer conn.Object(busName, s).Call("org.freedesktop.Secret.Session.Close", 0)
	properties := map[string]dbus.Variant{"org.freedesktop.Secret.Item.Label": dbus.MakeVariant("Meiju MCP local credential"), "org.freedesktop.Secret.Item.Attributes": dbus.MakeVariant(map[string]string{"service": "meiju-mcp.vault.v1", "account": key})}
	var created, prompt dbus.ObjectPath
	if object.Call("org.freedesktop.Secret.Collection.CreateItem", 0, properties, secret{s, []byte{}, value, "application/octet-stream"}, false).Store(&created, &prompt) != nil {
		return "storage_unavailable"
	}
	if prompt != "/" {
		return "storage_authorization_required"
	}
	return ""
}
func (nativeBackend) Delete(key string) string {
	conn, item, code := search(key)
	if code != "" || item == "" {
		return code
	}
	var prompt dbus.ObjectPath
	if conn.Object(busName, item).Call("org.freedesktop.Secret.Item.Delete", 0).Store(&prompt) != nil {
		return "storage_unavailable"
	}
	if prompt != "/" {
		return "storage_authorization_required"
	}
	return ""
}
