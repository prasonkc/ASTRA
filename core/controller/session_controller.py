"""
Session command handler module.
Handles all session-related commands for the chat interface.
"""
from ai.ollama import OllamaModel
from utils.colors import (
    Colors, error, success, warning, info, title, dim, user_msg, important, secondary, bold
)


class SessionController:
    def __init__(self, model: OllamaModel):
        self.model = model

    def handle(self, user_input: str) -> bool:
        """
        Handle a session command.
        Returns True if the command was handled, False otherwise.
        """
        try:
            parts = user_input.strip().split()
            
            if not parts:
                return False
            
            # Normalize /s to /session
            if parts[0] == "/s":
                parts[0] = "/session"
            
            if not parts[0].startswith("/session"):
                return False
            
            if len(parts) < 2:
                self._print_help()
                return True

            command = parts[1].lower()

            # Command dispatch
            handlers = {
                "new": self._cmd_new,
                "n": self._cmd_new,
                "list": self._cmd_list,
                "l": self._cmd_list,
                "ls": self._cmd_list,
                "switch": self._cmd_switch,
                "sw": self._cmd_switch,
                "s": self._cmd_switch,
                "use": self._cmd_switch,
                "u": self._cmd_switch,
                "resume": self._cmd_resume,
                "r": self._cmd_resume,
                "delete": self._cmd_delete,
                "del": self._cmd_delete,
                "rm": self._cmd_delete,
                "remove": self._cmd_delete,
                "d": self._cmd_delete,
                "clear": self._cmd_clear,
                "clr": self._cmd_clear,
                "purge": self._cmd_clear,
                "preview": self._cmd_preview,
                "p": self._cmd_preview,
                "show": self._cmd_preview,
                "info": self._cmd_preview,
                "help": self._print_help,
                "h": self._print_help,
                "?": self._print_help,
            }

            handler = handlers.get(command)
            if handler:
                handler(parts)
            else:
                # Try to parse as a number (quick switch)
                try:
                    index = int(command)
                    self._cmd_switch_by_index(index)
                except ValueError:
                    print(error(f"Unknown command: {command}"))
                    self._print_help()
            
            return True
        except EOFError:
            print("\n" + error("Input interrupted"))
            return True
        except KeyboardInterrupt:
            print("\n" + error("Command cancelled"))
            return True
        except Exception as e:
            print(error(f"Error handling session command: {e}"))
            return True

    def _cmd_new(self, parts):
        """Create new session (auto-switches)."""
        try:
            session_id = self.model.new_session()
            print(success(f"Created and switched to new session: {session_id}"))
            self._show_current_session()
        except Exception as e:
            print(error(f"Failed to create new session: {e}"))

    def _cmd_resume(self, parts):
        """Resume most recent session."""
        try:
            if self.model.resume_last_session():
                print(success("Resumed most recent session"))
                self._show_current_session()
            else:
                print(info("No previous sessions found. Use '/s new' to create one."))
        except Exception as e:
            print(error(f"Failed to resume session: {e}"))

    def _cmd_list(self, parts):
        """List all sessions with previews."""
        try:
            self._list_sessions()
        except Exception as e:
            print(error(f"Failed to list sessions: {e}"))

    def _cmd_switch(self, parts):
        """Switch to session by index or ID."""
        if len(parts) < 3:
            print("Usage: /s <number>  (see '/s list' for numbers)")
            return
        
        # Try index first
        try:
            index = int(parts[2])
            self._cmd_switch_by_index(index)
        except ValueError:
            # Fallback: try session_id for backward compatibility
            target_session = parts[2]
            try:
                if self.model.switch_session(target_session):
                    print(success(f"Switched to session: {target_session}"))
                    self._show_current_session()
                else:
                    print(error(f"Session not found: {target_session}"))
                    print("Use '/s list' to see available sessions with numbers.")
            except Exception as e:
                print(error(f"Failed to switch session: {e}"))

    def _cmd_switch_by_index(self, index: int):
        """Switch to session by index."""
        try:
            if index < 0:
                print(error("Session index must be non-negative"))
                return
            
            if self.model.switch_session_by_index(index):
                print(success(f"Switched to session #{index}"))
                self._show_current_session()
            else:
                print(error(f"No session at index {index}. Use '/s list' to see available sessions."))
        except Exception as e:
            print(error(f"Failed to switch session: {e}"))

    def _cmd_delete(self, parts):
        """Delete a session by index."""
        if len(parts) < 3:
            print("Usage: /s del <number>  (see '/s list' for numbers)")
            return
        
        try:
            index = int(parts[2])
            if index < 0:
                print(error("Session index must be non-negative"))
                return
                
            if self._confirm_delete(index):
                if self.model.delete_session_by_index(index):
                    print(success(f"Deleted session #{index}"))
                    # If we deleted current session, switch to most recent
                    try:
                        if self.model.chat_history.get_session_id_by_index(0) is None:
                            print(info("No sessions remaining."))
                        else:
                            self.model.resume_last_session()
                            self._show_current_session()
                    except Exception as e:
                        print(warning(f"Session deleted but failed to switch: {e}"))
                else:
                    print(error(f"No session at index {index}"))
        except ValueError:
            print(error("Please provide a valid session number (from '/s list')"))
        except Exception as e:
            print(error(f"Failed to delete session: {e}"))

    def _cmd_clear(self, parts):
        """Clear all sessions."""
        try:
            if self._confirm_clear():
                count = self.model.clear_all_sessions()
                print(success(f"Cleared all {count} sessions"))
                # Create a fresh session
                self.model.new_session()
                print(success("Created new empty session"))
                self._show_current_session()
        except Exception as e:
            print(error(f"Failed to clear sessions: {e}"))

    def _cmd_preview(self, parts):
        """Show preview of current or specified session."""
        try:
            if len(parts) >= 3:
                try:
                    index = int(parts[2])
                    if index < 0:
                        print(error("Session index must be non-negative"))
                        return
                    self._show_session_preview(index)
                except ValueError:
                    print(error("Usage: /s preview <number>"))
            else:
                self._show_session_preview(0)  # current session
        except Exception as e:
            print(error(f"Failed to show preview: {e}"))

    # Display helpers

    def _list_sessions(self):
        try:
            sessions = self.model.list_sessions_with_preview()
            if not sessions:
                print(info("No sessions found. Use '/s new' to create one."))
                return
            
            print("\n" + title("Sessions (most recent first):"))
            print(dim("─" * 70))
            for i, session in enumerate(sessions):
                current_marker = bold(" >") if session["session_id"] == self.model.session_id else "  "
                msg_count = session.get("message_count", 0)
                preview = session.get("preview", "(empty)")
                
                print(f"{current_marker} [{i}] {session['title']}")
                print(f"      {msg_count} messages  •  {session['updated_at']}")
                if preview != "(empty)":
                    first_line = preview.split('\n')[0]
                    print(f"      {dim(first_line)}")
                print()
            print(dim("─" * 70))
            print(dim("Use '/s <number>' to switch, '/s del <number>' to delete"))
        except Exception as e:
            print(error(f"Error listing sessions: {e}"))

    def _show_current_session(self):
        try:
            sessions = self.model.list_sessions_with_preview()
            if not sessions:
                return
            for i, session in enumerate(sessions):
                if session["session_id"] == self.model.session_id:
                    msg_count = session.get("message_count", 0)
                    print(info(f"Current: [{i}] {session['title']}  ({msg_count} messages)"))
                    break
        except Exception:
            # Silently fail for current session display
            pass

    def _show_session_preview(self, index: int):
        try:
            sessions = self.model.list_sessions_with_preview()
            if index >= len(sessions):
                print(error(f"No session at index {index}"))
                return
            
            session = sessions[index]
            current_marker = " (current)" if session["session_id"] == self.model.session_id else ""
            print(f"\n" + title(f"Session [{index}]{current_marker}: {session['title']}"))
            print(f"   Created: {session['created_at']}  •  Updated: {session['updated_at']}")
            print(f"   Messages: {session.get('message_count', 0)}")
            print(f"   ID: {session['session_id']}")
            print(dim("─" * 50))
            preview = session.get("preview", "(empty)")
            if preview != "(empty)":
                for line in preview.split('\n'):
                    print(f"   {line}")
            else:
                print(dim("   (empty)"))
            print(dim("─" * 50))
        except Exception as e:
            print(error(f"Error showing preview: {e}"))

    def _confirm_delete(self, index: int) -> bool:
        try:
            sessions = self.model.list_sessions_with_preview()
            if index >= len(sessions):
                return False
            session = sessions[index]
            confirm = input(warning(f"Delete session [{index}] '{session['title']}'? (y/N): ")).strip().lower()
            return confirm == 'y'
        except EOFError:
            print("\n" + error("Input cancelled"))
            return False
        except KeyboardInterrupt:
            print("\n" + error("Cancelled"))
            return False
        except Exception:
            return False

    def _confirm_clear(self) -> bool:
        try:
            sessions = self.model.list_sessions_with_preview()
            if not sessions:
                return False
            print(warning(f"This will delete ALL {len(sessions)} sessions permanently."))
            confirm = input(warning("Are you sure? Type 'YES' to confirm: ")).strip()
            return confirm == 'YES'
        except EOFError:
            print("\n" + error("Input cancelled"))
            return False
        except KeyboardInterrupt:
            print("\n" + error("Cancelled"))
            return False
        except Exception:
            return False

    def _print_help(self, parts=None):
        print(f"""
{title("Session Commands (shorthand: /s)")}

  /s new              Create new session (auto-switches)
  /s list             List all sessions with previews
  /s <number>         Quick switch to session by number
  /s switch <number>  Switch to session by number  
  /s resume           Resume most recent session
  /s del <number>     Delete a session (with confirmation)
  /s clear            Delete ALL sessions (with confirmation)
  /s preview [num]    Show conversation preview (default: current)
  /s help             Show this help

Examples:
  /s new
  /s list
  /s 0                # Switch to most recent
  /s 2                # Switch to session #2
  /s del 1            # Delete session #1
  /s clear            # Delete everything
        """.strip())