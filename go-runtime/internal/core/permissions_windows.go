//go:build windows

package core

import (
	"golang.org/x/sys/windows"
	"os"
	"unsafe"
)

func userSID() (*windows.SID, error) {
	t := windows.GetCurrentProcessToken()
	u, e := t.GetTokenUser()
	if e != nil {
		return nil, e
	}
	return u.User.Sid, nil
}
func restrictNew(path string, dir bool) error {
	sid, e := userSID()
	if e != nil {
		return e
	}
	flags := ""
	if dir {
		flags = "OICI"
	}
	sd, e := windows.SecurityDescriptorFromString("O:" + sid.String() + "D:P(A;" + flags + ";FA;;;" + sid.String() + ")")
	if e != nil {
		return e
	}
	acl, _, e := sd.DACL()
	if e != nil {
		return e
	}
	return windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, sid, nil, acl, nil)
}
func checkPrivate(path string, fi os.FileInfo) error {
	p, e := windows.UTF16PtrFromString(path)
	if e != nil {
		return Err("storage_unsafe")
	}
	attrs, e := windows.GetFileAttributes(p)
	if e != nil || attrs&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return Err("storage_unsafe")
	}
	sid, e := userSID()
	if e != nil {
		return Err("storage_unsafe")
	}
	sd, e := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if e != nil {
		return Err("storage_unsafe")
	}
	owner, _, e := sd.Owner()
	if e != nil || !owner.Equals(sid) {
		return Err("storage_unsafe")
	}
	acl, _, e := sd.DACL()
	if e != nil || acl == nil {
		return Err("storage_unsafe")
	}
	for i := uint32(0); i < uint32(acl.AceCount); i++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if windows.GetAce(acl, i, &ace) != nil || ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE {
			return Err("storage_unsafe")
		}
		allowed := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
		if !allowed.Equals(sid) {
			return Err("storage_unsafe")
		}
	}
	return nil
}
