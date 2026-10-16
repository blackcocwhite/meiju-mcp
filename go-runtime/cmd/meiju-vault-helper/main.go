package main

import (
	"fmt"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/vaultworker"
	"os"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--identity" {
		fmt.Println(`{"identifier":"local.meiju.mcp.vault-helper","protocol":1,"backend":"meiju-vault-v1"}`)
		return
	}
	if len(os.Args) > 2 || len(os.Args) == 2 && os.Args[1] != "--authorize" {
		os.Exit(2)
	}
	if vaultworker.Run(os.Stdin, os.Stdout) != nil {
		os.Exit(1)
	}
}
