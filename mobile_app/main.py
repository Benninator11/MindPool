import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import flet as ft

from engine.llama_runner import ChatMessage, LlamaRunner, LlamaServerConfig


class MindPoolApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.runner: Optional[LlamaRunner] = None
        self.model_path: Optional[Path] = None
        self.messages: list[ChatMessage] = []
        self.is_streaming = False

        self._setup_page()
        self._build_ui()

    def _setup_page(self):
        self.page.title = "MindPool"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#000000"
        self.page.padding = 0
        self.page.window_width = 400
        self.page.window_height = 800

        self.page.theme = ft.Theme(
            color_scheme_seed="#89A8D8",
            visual_density=ft.VisualDensity.COMFORTABLE,
        )

    def _build_ui(self):
        self.chat_list = ft.ListView(
            expand=True,
            spacing=12,
            padding=ft.padding.all(16),
            auto_scroll=True,
        )

        self.input_field = ft.TextField(
            hint_text="Nachricht eingeben...",
            border_color="#7B52C7",
            focused_border_color="#89A8D8",
            bgcolor="#0A0A0A",
            color="#FFFFFF",
            cursor_color="#89A8D8",
            multiline=True,
            min_lines=1,
            max_lines=5,
            expand=True,
            on_submit=self._on_send,
        )

        self.send_btn = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_color="#89A8D8",
            on_click=self._on_send,
            disabled=False,
        )

        self.status_text = ft.Text(
            "Bereit - Wähle ein Modell",
            size=12,
            color="#7B52C7",
        )

        self.model_dropdown = ft.Dropdown(
            label="Modell",
            border_color="#7B52C7",
            focused_border_color="#89A8D8",
            bgcolor="#0A0A0A",
            color="#FFFFFF",
            options=[],
            width=200,
            on_change=self._on_model_change,
        )

        self._scan_models()

        top_bar = ft.Container(
            content=ft.Row(
                [
                    ft.Text("MindPool", size=20, weight=ft.FontWeight.BOLD, color="#89A8D8"),
                    ft.Container(expand=True),
                    self.model_dropdown,
                    self.status_text,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            bgcolor="#050505",
            border=ft.border.only(bottom=ft.BorderSide(1, "#1A1A1A")),
        )

        input_row = ft.Container(
            content=ft.Row(
                [self.input_field, self.send_btn],
                spacing=8,
            ),
            padding=ft.padding.all(16),
            bgcolor="#050505",
            border=ft.border.only(top=ft.BorderSide(1, "#1A1A1A")),
        )

        self.page.add(
            ft.Column(
                [top_bar, self.chat_list, input_row],
                expand=True,
                spacing=0,
            )
        )

    def _scan_models(self):
        models_dir = Path.home() / ".mindpool" / "models"
        if models_dir.exists():
            gguf_files = list(models_dir.glob("*.gguf"))
            self.model_dropdown.options = [
                ft.dropdown.Option(f.name, f.name) for f in gguf_files
            ]
            if gguf_files:
                self.model_dropdown.value = gguf_files[0].name
                self.model_path = gguf_files[0]
            self.page.update()

    def _on_model_change(self, e):
        if e.control.value:
            self.model_path = Path.home() / ".mindpool" / "models" / e.control.value
            self.status_text.value = f"Modell: {e.control.value}"
            self.page.update()

    async def _on_send(self, e):
        if self.is_streaming or not self.input_field.value.strip():
            return

        if not self.model_path:
            self._add_message("System", "Bitte wähle zuerst ein Modell aus.", is_system=True)
            return

        user_text = self.input_field.value.strip()
        self.input_field.value = ""
        self.send_btn.disabled = True
        self.is_streaming = True
        self.page.update()

        self._add_message("Du", user_text)
        self.messages.append(ChatMessage(role="user", content=user_text))

        await self._stream_response()

        self.send_btn.disabled = False
        self.is_streaming = False
        self.page.update()

    async def _stream_response(self):
        if not self.runner:
            config = LlamaServerConfig(model_path=self.model_path)
            self.runner = LlamaRunner(config)

        if not self.runner.is_running():
            self.status_text.value = "Starte llama-server..."
            self.page.update()
            if not await self.runner.start():
                self._add_message("System", "Fehler: llama-server konnte nicht gestartet werden.", is_system=True)
                self.status_text.value = "Fehler beim Start"
                return

        self.status_text.value = "Generiere Antwort..."
        self.page.update()

        assistant_msg = ft.Text("", color="#FFFFFF", selectable=True)
        msg_container = self._create_message_container("MindPool", assistant_msg)
        self.chat_list.controls.append(msg_container)
        self.page.update()

        full_response = ""
        try:
            async for chunk in self.runner.chat_completion(
                self.messages,
                temperature=0.7,
                top_p=0.95,
                top_k=40,
                max_tokens=2048,
            ):
                full_response += chunk
                assistant_msg.value = full_response
                self.page.update()
        except RuntimeError as err:
            if "ERR_MODEL_CAPACITY_EXHAUSTED" in str(err):
                assistant_msg.value = "⚠ Modell überlastet. Bitte kleineres Modell wählen."
                assistant_msg.color = "#FF6B6B"
            else:
                assistant_msg.value = f"Fehler: {err}"
                assistant_msg.color = "#FF6B6B"
        except Exception as err:
            assistant_msg.value = f"Fehler: {err}"
            assistant_msg.color = "#FF6B6B"
        finally:
            if full_response:
                self.messages.append(ChatMessage(role="assistant", content=full_response))
            self.status_text.value = "Bereit"

        self.page.update()

    def _add_message(self, sender: str, content: str, is_system: bool = False):
        msg_text = ft.Text(content, color="#FF6B6B" if is_system else "#FFFFFF", selectable=True)
        container = self._create_message_container(sender, msg_text, is_system)
        self.chat_list.controls.append(container)
        self.page.update()

    def _create_message_container(self, sender: str, content_control: ft.Control, is_system: bool = False) -> ft.Container:
        sender_color = "#7B52C7" if is_system else "#89A8D8"
        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(sender, size=12, color=sender_color, weight=ft.FontWeight.W_500),
                        ],
                        spacing=8,
                    ),
                    content_control,
                ],
                spacing=4,
            ),
            padding=ft.padding.all(12),
            bgcolor="#0A0A0A" if not is_system else "#1A0A0A",
            border_radius=12,
            border=ft.border.all(1, "#1A1A1A") if not is_system else ft.border.all(1, "#3A1A1A"),
        )


async def main(page: ft.Page):
    app = MindPoolApp(page)

    def on_close(_):
        if app.runner:
            app.runner.stop_sync()

    page.on_close = on_close


if __name__ == "__main__":
    ft.app(target=main, view=ft.AppView.FLET_APP)
