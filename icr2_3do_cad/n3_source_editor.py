"""Embedded Papyrus N3 source editor: syntax, diagnostics and debounced live preview.

All Tk calls stay on the UI thread. Compilation runs in a single background
worker; revisions discard stale results and preserve the last valid viewport.
"""
from __future__ import annotations

from pathlib import Path
from queue import Queue, Empty
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from n3_compile import compile_n3_text
from three_do import FormatError

LEX_RE = re.compile(
    r'(?P<comment>%[^\n]*)|(?P<string>"[^"\n]*")|'
    r'(?P<keyword>\b(?:3D|VERSION|NIL|POLY|LINE|LIST|FACE2?|BSPF|BSPA|BSP2|BSPN|MATERIAL|GROUP|MIP|SWITCH|DISTANCE|DYNAMIC|EXTERN|SUPEROBJ|PMP2|SRB|RECOLOR|DYNO|DATA)\b)|'
    r'(?P<label>^[ \t]*[A-Za-z_][A-Za-z_0-9]*(?=[ \t]*:))',
    re.I | re.M,
)


def find_error_line(source: str, error: str) -> int:
    """Find the most specific relevant line, avoiding jumps to line 1."""
    m=re.search(r'\bline\s+(\d+)\b', error, re.I)
    if m:
        return max(1,int(m.group(1)))
    m=re.search(r"(?:in|at)\s+(?:record|label)\s+['\"]?([A-Za-z_][\w]*)", error, re.I)
    if m:
        token=m.group(1)
        match=re.search(r'(?m)^\s*'+re.escape(token)+r'\s*:',source)
        if match:return source.count("\n",0,match.start())+1
    m=re.search(r'(?:unresolved N3 pointer|unknown plane vertex):?\s*[\'"]?([A-Za-z_][\w]*)',error,re.I)
    if m:
        token=m.group(1)
        match=re.search(r'(?<![\w])'+re.escape(token)+r'(?![\w])',source)
        if match:return source.count("\n",0,match.start())+1
    return 1


class SourceEditor(ttk.Frame):
    """Tk source pane that never shows a half-parsed model."""
    def __init__(self, parent, *, on_valid, on_invalid):
        super().__init__(parent)
        self.on_valid=on_valid
        self.on_invalid=on_invalid
        self.source_path=Path("new_model.3d")
        self._raw_text=""
        self._line_ending="\n"
        self._changed=False
        self._rev=0
        self._applied_rev=0
        self._job=None
        self._poll_job=None
        self._highlight_job=None
        self._worker_busy=False
        self._results=Queue()
        self._closed=False
        self._setting=False
        self.message=tk.StringVar(value="Open a .3D or .3DO to edit its N3 source.")
        self.position=tk.StringVar(value="Line 1, column 1")
        top=ttk.Frame(self);top.pack(fill="x",padx=6,pady=6)
        ttk.Button(top,text="Apply now",command=self.apply_now).pack(side="left",padx=(0,4))
        ttk.Button(top,text="Save .3D…",command=self.save_source).pack(side="left",padx=(0,4))
        ttk.Button(top,text="Find error",command=self.go_to_error).pack(side="left")
        tk.Label(self,textvariable=self.message,bg="#222a38",fg="#cbd6e7",
                 wraplength=360,justify="left",anchor="w",
                 font=("Segoe UI",9)).pack(fill="x",padx=8,pady=(0,5))
        editor=tk.Frame(self,bg="#101622")
        editor.pack(fill="both",expand=True,padx=5,pady=3)
        sy=ttk.Scrollbar(editor,orient="vertical")
        sx=ttk.Scrollbar(editor,orient="horizontal")
        self.text=tk.Text(editor,wrap="none",undo=True,autoseparators=True,
                    maxundo=200,background="#101622",foreground="#e8edf6",
                    insertbackground="#f6f8fb",selectbackground="#34577d",
                    font=("Consolas",10),padx=8,pady=7,
                    yscrollcommand=sy.set,xscrollcommand=sx.set,
                    tabs=("20c","32c"))
        sy.configure(command=self.text.yview)
        sx.configure(command=self.text.xview)
        sy.pack(side="right",fill="y")
        sx.pack(side="bottom",fill="x")
        self.text.pack(side="left",fill="both",expand=True)
        self.text.tag_configure("comment",foreground="#6da285")
        self.text.tag_configure("string",foreground="#dfb17f")
        self.text.tag_configure("keyword",foreground="#91b8f4")
        self.text.tag_configure("label",foreground="#e7d38e")
        self.text.tag_configure("error",background="#5b2632",foreground="#ffffff")
        self.text.tag_configure("error_mark",underline=True,foreground="#ff7988")
        ttk.Label(self,textvariable=self.position).pack(fill="x",padx=8,pady=(0,4))
        self.text.bind("<<Modified>>",self._edited)
        self.text.bind("<KeyRelease>",self._cursor)
        self.text.bind("<ButtonRelease-1>",self._cursor)
        self.text.edit_modified(False)

    def get_source(self):
        if not self._changed:
            return self._raw_text
        value=self.text.get("1.0","end-1c")
        if self._line_ending=="\r\n":
            return value.replace("\n","\r\n")
        return value

    def set_source(self, text, *, path=None, status="N3 source is ready; edit to preview"):
        """Refresh after loading or a visual-tab edit, without firing a new compile."""
        self._cancel_pending()
        self._rev+=1
        self._applied_rev=self._rev
        self._raw_text=str(text)
        self._line_ending="\r\n" if "\r\n" in text else "\n"
        self._changed=False
        if path is not None:self.source_path=Path(path)
        self._setting=True
        try:
            self.text.delete("1.0","end")
            self.text.insert("1.0",text.replace("\r\n","\n"))
            self.text.edit_modified(False)
        finally:
            self._setting=False
        self.text.tag_remove("error","1.0","end")
        self.message.set(status)
        self._schedule_highlight()

    @property
    def pending(self):
        return self._changed and self._rev!=self._applied_rev

    def _cancel_pending(self):
        if self._job is not None:
            self.after_cancel(self._job);self._job=None

    def _edited(self,event=None):
        if self._setting:return
        if not self.text.edit_modified():return
        self.text.edit_modified(False)
        self._changed=True
        self._rev+=1
        self._cancel_pending()
        self._job=self.after(650,self._start_background)
        self.message.set("Editing… preview retains the last valid model until parsing succeeds.")
        self._schedule_highlight()
        self._cursor()

    def _cursor(self,event=None):
        line,col=self.text.index("insert").split(".")
        self.position.set(f"Line {line}, column {int(col)+1}")

    def _schedule_highlight(self):
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job=self.after(280,self._highlight)

    def _highlight(self):
        self._highlight_job=None
        if self._closed:return
        for name in ("comment","string","keyword","label"):
            self.text.tag_remove(name,"1.0","end")
        # Limit Tk tag operations, not the underlying source or parser.
        sample=self.text.get("1.0","1001.0")
        for i,m in enumerate(LEX_RE.finditer(sample)):
            if i>=4000:break
            tag=m.lastgroup
            self.text.tag_add(tag,f"1.0+{m.start()}c",f"1.0+{m.end()}c")
        self.text.tag_raise("error")

    def _start_background(self):
        self._job=None
        if self._closed or not self._changed or self._rev<=self._applied_rev:return
        if self._worker_busy:
            # A newer revision will be picked up when the worker finishes.
            return
        rev=self._rev
        source=self.get_source()
        path=self.source_path
        self._worker_busy=True
        self.message.set("Parsing .3D and updating preview…")
        def work():
            try:
                model,doc=compile_n3_text(source,path)
                result=(rev,source,model,doc,None)
            except (FormatError,ValueError,OverflowError,UnicodeError) as exc:
                result=(rev,source,None,None,str(exc))
            except Exception as exc:
                result=(rev,source,None,None,f"Unexpected compiler error: {exc}")
            self._results.put(result)
        threading.Thread(target=work,daemon=True,name="n3-cad-preview").start()
        if self._poll_job is None:self._poll_job=self.after(55,self._poll)

    def _poll(self):
        self._poll_job=None
        if self._closed:return
        try:
            revision,source,model,doc,error=self._results.get_nowait()
        except Empty:
            if self._worker_busy:self._poll_job=self.after(60,self._poll)
            return
        self._worker_busy=False
        if revision!=self._rev or revision<=self._applied_rev:
            # A successful manual Apply also supersedes in-flight parses.
            if self._changed and self._rev>self._applied_rev:
                self._start_background()
            return
        self._accept(revision,source,model,doc,error)

    def _accept(self,revision,source,model,doc,error):
        self._applied_rev=revision
        self.text.tag_remove("error","1.0","end")
        if error:
            lineno=find_error_line(source,error)
            self.text.tag_add("error",f"{lineno}.0",f"{lineno}.end")
            self.message.set(f"Line {lineno}: {error}. Last valid preview retained.")
            self.on_invalid(error,lineno)
        else:
            self.message.set(f"Valid N3 • {len(model.vertices)} vertices • "
                             f"{len(model.polygons)} polygons • XYZ ×"
                             f"{getattr(model,'n3_coordinate_scale',1)} • live preview")
            self.on_valid(model,doc,source)

    def apply_now(self):
        """Synchronous user action (also used to prevent saving stale previews)."""
        if not self._changed or self._rev==self._applied_rev:
            return self.message.get().startswith("Valid N3") or not self._changed
        self._cancel_pending()
        revision=self._rev
        source=self.get_source()
        try:
            model,doc=compile_n3_text(source,self.source_path)
        except (FormatError,ValueError,OverflowError,UnicodeError) as exc:
            self._accept(revision,source,None,None,str(exc))
            return False
        self._accept(revision,source,model,doc,None)
        return True

    def go_to_error(self):
        spans=self.text.tag_ranges("error")
        if spans:
            self.text.mark_set("insert",spans[0])
            self.text.see(spans[0]);self.text.focus_set()

    def save_source(self):
        source=self.get_source()
        target=filedialog.asksaveasfilename(title="Save editable N3 text",defaultextension=".3d",
            initialfile=self.source_path.stem+"_edited.3d",
            initialdir=str(self.source_path.parent),
            filetypes=[("Papyrus N3 .3D","*.3d"),("All files","*.*")])
        if not target:return
        path=Path(target)
        if path.resolve()==self.source_path.resolve():
            if not messagebox.askyesno("Overwrite original N3 source?",
                   "This will overwrite your original editable .3D source. Continue?",default="no"):
                return
        try:
            path.write_bytes(source.encode("utf-8"))
        except (OSError,UnicodeError) as exc:
            messagebox.showerror("Could not save N3 text",str(exc));return
        self.message.set(f"Saved source text to {path.name}."+
                         (" The preview may still be invalid." if self.pending else ""))

    def close(self):
        self._closed=True
        self._cancel_pending()
        for job in (self._poll_job,self._highlight_job):
            if job is not None:
                try:self.after_cancel(job)
                except tk.TclError:pass
        self._poll_job=None
        self._highlight_job=None
