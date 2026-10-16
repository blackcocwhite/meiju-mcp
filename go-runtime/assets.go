package runtimeassets

import "embed"

//go:embed contract/* web/*
var Files embed.FS
