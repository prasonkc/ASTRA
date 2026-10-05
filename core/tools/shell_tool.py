"""
Shell tool for ASTRA - provides safe shell command execution capabilities.
"""
import subprocess
import os
import shlex
from pathlib import Path
from typing import Dict, Any, List, Optional
from utils.colors import warning, error


class ShellTool:
    def __init__(self, allowed_commands: Optional[List[str]] = None, 
                 working_dir: Optional[str] = None,
                 timeout: int = 30):
        """
        Initialize shell tool.
        
        Args:
            allowed_commands: List of allowed command names (None = allow all)
            working_dir: Default working directory (None = current directory)
            timeout: Command timeout in seconds
        """
        self.allowed_commands = allowed_commands
        self.working_dir = working_dir or os.getcwd()
        self.timeout = timeout
        
        self.functions = {
            "shell_exec": self.exec,
            "shell_read": self.read_file,
            "shell_write": self.write_file,
            "shell_list": self.list_dir,
            "shell_glob": self.glob_files,
            "shell_exists": self.path_exists,
        }

    def _validate_command(self, command: str) -> bool:
        """Validate if command is allowed."""
        if self.allowed_commands is None:
            return True
        
        # Extract command name (first word)
        parts = shlex.split(command)
        if not parts:
            return False
        cmd_name = parts[0]
        
        # Check if base command is allowed (e.g., "ls" from "ls -la")
        base_cmd = os.path.basename(cmd_name)
        return base_cmd in self.allowed_commands or cmd_name in self.allowed_commands

    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to working directory."""
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.working_dir) / p
        return p.resolve()

    def exec(self, command: str, cwd: Optional[str] = None, 
             timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute a shell command.
        
        Args:
            command: Command to execute
            cwd: Working directory (optional)
            timeout: Timeout in seconds (optional)
        
        Returns:
            Dict with success, stdout, stderr, returncode
        """
        if not self._validate_command(command):
            return {
                "success": False,
                "error": f"Command not allowed: {command}",
                "stdout": "",
                "stderr": "",
                "returncode": -1
            }
        
        try:
            work_dir = cwd or self.working_dir
            result = subprocess.run(
                command,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout or self.timeout}s",
                "stdout": "",
                "stderr": "",
                "returncode": -1
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Execution error: {str(e)}",
                "stdout": "",
                "stderr": "",
                "returncode": -1
            }

    def read_file(self, path: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """
        Read a file.
        
        Args:
            path: File path (relative to working dir or absolute)
            encoding: File encoding
        
        Returns:
            Dict with success, content, error
        """
        try:
            file_path = self._resolve_path(path)
            
            # Safety: prevent reading outside working dir (optional)
            # if not str(file_path).startswith(str(Path(self.working_dir).resolve())):
            #     return {"success": False, "error": "Path outside working directory"}
            
            if not file_path.exists():
                return {"success": False, "error": f"File not found: {path}"}
            
            if not file_path.is_file():
                return {"success": False, "error": f"Not a file: {path}"}
            
            content = file_path.read_text(encoding=encoding)
            return {
                "success": True,
                "content": content,
                "path": str(file_path)
            }
        except Exception as e:
            return {"success": False, "error": f"Read error: {str(e)}"}

    def write_file(self, path: str, content: str, encoding: str = "utf-8",
                   create_dirs: bool = True) -> Dict[str, Any]:
        """
        Write a file.
        
        Args:
            path: File path (relative to working dir or absolute)
            content: Content to write
            encoding: File encoding
            create_dirs: Create parent directories if they don't exist
        
        Returns:
            Dict with success, path, error
        """
        try:
            file_path = self._resolve_path(path)
            
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_path.write_text(content, encoding=encoding)
            return {
                "success": True,
                "path": str(file_path),
                "bytes_written": len(content.encode(encoding))
            }
        except Exception as e:
            return {"success": False, "error": f"Write error: {str(e)}"}

    def list_dir(self, path: str = ".", show_hidden: bool = False) -> Dict[str, Any]:
        """
        List directory contents.
        
        Args:
            path: Directory path (relative to working dir or absolute)
            show_hidden: Include hidden files
        
        Returns:
            Dict with success, entries, error
        """
        try:
            dir_path = self._resolve_path(path)
            
            if not dir_path.exists():
                return {"success": False, "error": f"Directory not found: {path}"}
            
            if not dir_path.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}
            
            entries = []
            for entry in sorted(dir_path.iterdir()):
                if not show_hidden and entry.name.startswith('.'):
                    continue
                
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })
            
            return {
                "success": True,
                "path": str(dir_path),
                "entries": entries
            }
        except Exception as e:
            return {"success": False, "error": f"List error: {str(e)}"}

    def glob_files(self, pattern: str, path: str = ".") -> Dict[str, Any]:
        """
        Find files matching a glob pattern.
        
        Args:
            pattern: Glob pattern (e.g., "*.py", "**/*.txt")
            path: Base directory path
        
        Returns:
            Dict with success, matches, error
        """
        try:
            base_path = self._resolve_path(path)
            matches = []
            
            for match in base_path.glob(pattern):
                if match.is_file():
                    stat = match.stat()
                    matches.append({
                        "name": match.name,
                        "path": str(match),
                        "relative_path": str(match.relative_to(base_path)),
                        "size": stat.st_size,
                        "modified": stat.st_mtime
                    })
            
            return {
                "success": True,
                "pattern": pattern,
                "base_path": str(base_path),
                "matches": matches
            }
        except Exception as e:
            return {"success": False, "error": f"Glob error: {str(e)}"}

    def path_exists(self, path: str) -> Dict[str, Any]:
        """
        Check if a path exists and get its type.
        
        Args:
            path: Path to check
        
        Returns:
            Dict with success, exists, type, error
        """
        try:
            file_path = self._resolve_path(path)
            exists = file_path.exists()
            
            result = {"success": True, "exists": exists, "path": str(file_path)}
            
            if exists:
                if file_path.is_file():
                    result["type"] = "file"
                elif file_path.is_dir():
                    result["type"] = "dir"
                else:
                    result["type"] = "other"
            
            return result
        except Exception as e:
            return {"success": False, "error": f"Exists check error: {str(e)}"}

    def get_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions for function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "shell_exec",
                    "description": "Execute a shell command and return its output",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Shell command to execute"
                            },
                            "cwd": {
                                "type": "string",
                                "description": "Working directory (optional)"
                            },
                            "timeout": {
                                "type": "integer",
                                "description": "Timeout in seconds (optional)"
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shell_read",
                    "description": "Read a file and return its contents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to read"
                            },
                            "encoding": {
                                "type": "string",
                                "description": "File encoding (default: utf-8)"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shell_write",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path to write"
                            },
                            "content": {
                                "type": "string",
                                "description": "Content to write"
                            },
                            "encoding": {
                                "type": "string",
                                "description": "File encoding (default: utf-8)"
                            },
                            "create_dirs": {
                                "type": "boolean",
                                "description": "Create parent directories if needed (default: true)"
                            }
                        },
                        "required": ["path", "content"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shell_list",
                    "description": "List directory contents",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Directory path to list"
                            },
                            "show_hidden": {
                                "type": "boolean",
                                "description": "Include hidden files (default: false)"
                            }
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shell_glob",
                    "description": "Find files matching a glob pattern",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Glob pattern (e.g., *.py, **/*.txt)"
                            },
                            "path": {
                                "type": "string",
                                "description": "Base directory path"
                            }
                        },
                        "required": ["pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "shell_exists",
                    "description": "Check if a path exists and get its type",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Path to check"
                            }
                        },
                        "required": ["path"]
                    }
                }
            }
        ]