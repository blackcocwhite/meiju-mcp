package service

import (
	"context"
	"encoding/json"
	assets "github.com/blackcocwhite/meiju-mcp/go-runtime"
	"github.com/blackcocwhite/meiju-mcp/go-runtime/internal/core"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/santhosh-tekuri/jsonschema/v6"
)

const BuildVersion = "0.2.1+go-dev"

type Caller func(context.Context, string, core.Object) (*mcp.CallToolResult, error)

func Result(v core.Object, err error) *mcp.CallToolResult {
	if err != nil {
		var safe any = core.Object{"error": "internal_error", "message": "操作未完成，请检查服务状态。"}
		if e, ok := err.(*core.SafeError); ok {
			safe = e
		}
		b, _ := core.JSON(safe)
		return &mcp.CallToolResult{IsError: true, Content: []mcp.Content{&mcp.TextContent{Text: string(b)}}}
	}
	b, _ := core.JSON(v)
	return &mcp.CallToolResult{StructuredContent: v, Content: []mcp.Content{&mcp.TextContent{Text: string(b)}}}
}
func NewMCP(call Caller) (*mcp.Server, error) {
	instructions, _ := assets.Files.ReadFile("contract/instructions.txt")
	server := mcp.NewServer(&mcp.Implementation{Name: "meiju-mcp", Version: BuildVersion}, &mcp.ServerOptions{Instructions: string(instructions)})
	b, _ := assets.Files.ReadFile("contract/tools.json")
	var tools []*mcp.Tool
	if e := json.Unmarshal(b, &tools); e != nil {
		return nil, e
	}
	for _, tool := range tools {
		compiler := jsonschema.NewCompiler()
		raw, _ := json.Marshal(tool.InputSchema)
		var schemaData any
		_ = json.Unmarshal(raw, &schemaData)
		if e := compiler.AddResource("schema.json", schemaData); e != nil {
			return nil, e
		}
		schema, e := compiler.Compile("schema.json")
		if e != nil {
			return nil, e
		}
		name := tool.Name
		server.AddTool(tool, func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			raw := req.Params.Arguments
			if len(raw) == 0 {
				raw = []byte("{}")
			}
			var args core.Object
			if core.Decode(raw, &args) != nil || args == nil || schema.Validate(args) != nil {
				return Result(nil, core.Err("invalid_input")), nil
			}
			return call(ctx, name, args)
		})
	}
	return server, nil
}
func LocalCaller(e *core.Engine, p *Portal) Caller {
	return func(ctx context.Context, name string, args core.Object) (*mcp.CallToolResult, error) {
		if name == "meiju_login" {
			v, err := p.Start()
			return Result(v, err), nil
		}
		if name == "meiju_logout" {
			p.Invalidate()
		}
		v, err := e.Call(ctx, name, args)
		return Result(v, err), nil
	}
}
