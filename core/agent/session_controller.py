"""
Session command handler module.
Handles all session-related commands for the chat interface.
"""
from ai.ollama import OllamaModel


class SessionController:
    def __init__(self, model: OllamaModel):
        self.model = model

    def handle(self, user_input: str) -> bool:
        """
        Handle a session command.
        Returns True if the command was handled, False otherwise.
        """
        parts = user_input.strip().split()
        
        # Normalize /s to /session
        if parts and parts[0] == "/s":
            parts[0] = "/session"
        
        if not parts or not parts[0].startswith("/session"):
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
                print(f"Unknown command: {command}")
                self._print_help()
        
        return True

    def _cmd_new(self, parts):
        """Create new session (auto-switches)."""
        session_id = self.model.new_session()
        print(f"Created and switched to new session: {session_id}")
        self._show_current_session()

    def _cmd_resume(self, parts):
        """Resume most recent session."""
        if self.model.resume_last_session():
            print(f"Resumed most recent session")
            self._show_current_session()
        else:
            print("No previous sessions found. Use '/s new' to create one.")

    def _cmd_list(self, parts):
        """List all sessions with previews."""
        self._list_sessions()

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
            if self.model.switch_session(target_session):
                print(f"Switched to session: {target_session}")
                self._show_current_session()
            else:
                print(f"Session not found: {target_session}")
                print("Use '/s list' to see available sessions with numbers.")

    def _cmd_switch_by_index(self, index: int):
        """Switch to session by index."""
        if self.model.switch_session_by_index(index):
            print(f"Switched to session #{index}")
            self._show_current_session()
        else:
            print(f"No session at index {index}. Use '/s list' to see available sessions.")

    def _cmd_delete(self, parts):
        """Delete a session by index."""
        if len(parts) < 3:
            print("Usage: /s del <number>  (see '/s list' for numbers)")
            return
        
        try:
            index = int(parts[2])
            if self._confirm_delete(index):
                if self.model.delete_session_by_index(index):
                    print(f"Deleted session #{index}")
                    # If we deleted current session, switch to most recent
                    if self.model.chat_history.get_session_id_by_index(0) is None:
                        print("No sessions remaining.")
                    else:
                        self.model.resume_last_session()
                        self._show_current_session()
                else:
                    print(f"No session at index {index}")
        except ValueError:
            print("Please provide a session number (from '/s list')")

    def _cmd_clear(self, parts):
        """Clear all sessions."""
        if self._confirm_clear():
            count = self.model.clear_all_sessions()
            print(f"Cleared all {count} sessions")
            # Create a fresh session
            self.model.new_session()
            print("Created new empty session")
            self._show_current_session()

    def _cmd_preview(self, parts):
        """Show preview of current or specified session."""
        if len(parts) >= 3:
            try:
                index = int(parts[2])
                self._show_session_preview(index)
            except ValueError:
                print("Usage: /s preview <number>")
        else:
            self._show_session_preview(0)  # current session

    # Display helpers

    def _list_sessions(self):
        sessions = self.model.list_sessions_with_preview()
        if not sessions:
            print("No sessions found. Use '/s new' to create one.")
            return
        
        print("\n📋 Sessions (most recent first):")
        print("─" * 70)
        for i, session in enumerate(sessions):
            current_marker = " ►" if session["session_id"] == self.model.session_id else "  "
            msg_count = session.get("message_count", 0)
            preview = session.get("preview", "(empty)")
            
            print(f"{current_marker} [{i}] {session['title']}")
            print(f"      {msg_count} messages  •  {session['updated_at']}")
            if preview != "(empty)":
                first_line = preview.split('\n')[0]
                print(f"      💬 {first_line}")
            print()
        print("─" * 70)
        print("Use '/s <number>' to switch, '/s del <number>' to delete")

    def _show_current_session(self):
        sessions = self.model.list_sessions_with_preview()
        if not sessions:
            return
        for i, session in enumerate(sessions):
            if session["session_id"] == self.model.session_id:
                msg_count = session.get("message_count", 0)
                print(f"📍 Current: [{i}] {session['title']}  ({msg_count} messages)")
                break

    def _show_session_preview(self, index: int):
        sessions = self.model.list_sessions_with_preview()
        if index >= len(sessions):
            print(f"No session at index {index}")
            return
        
        session = sessions[index]
        current_marker = " (current)" if session["session_id"] == self.model.session_id else ""
        print(f"\n📖 Session [{index}]{current_marker}: {session['title']}")
        print(f"   Created: {session['created_at']}  •  Updated: {session['updated_at']}")
        print(f"   Messages: {session.get('message_count', 0)}")
        print(f"   ID: {session['session_id']}")
        print("─" * 50)
        preview = session.get("preview", "(empty)")
        if preview != "(empty)":
            for line in preview.split('\n'):
                print(f"   {line}")
        else:
            print("   (empty)")
        print("─" * 50)

    def _confirm_delete(self, index: int) -> bool:
        sessions = self.model.list_sessions_with_preview()
        if index >= len(sessions):
            return False
        session = sessions[index]
        confirm = input(f"Delete session [{index}] '{session['title']}'? (y/N): ").strip().lower()
        return confirm == 'y'

    def _confirm_clear(self) -> bool:
        sessions = self.model.list_sessions_with_preview()
        if not sessions:
            return False
        print(f"This will delete ALL {len(sessions)} sessions permanently.")
        confirm = input("Are you sure? Type 'YES' to confirm: ").strip()
        return confirm == 'YES'

    def _print_help(self):
        print("""
📁 Session Commands (shorthand: /s)

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