"""ICR2 3DO CAD: vertex and polygon editor with lossless 3DO output."""
from __future__ import annotations
import argparse
import colorsys
from collections import OrderedDict
import math
import os
import tempfile
from time import perf_counter
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from three_do import Model, FormatError, dot, sub, cross, NAMES, PlaneEdit, polygon_triplet_refs
from car_appearance import read_car_appearance, locate_base_geometry, AppearanceError
from texture_preview import ENABLED as TEXTURE_AVAILABLE, load_mip, TextureError, rasterize_polygon
from dynamic_scene import ExternalResolver, Transform, gather_faces, RenderSprite, degrees_to_papyrus, papyrus_to_degrees
from pmp_preview import load_pmp, PMPError
from text_3d import export_text, import_text, parse_document, export_standalone_text
from n3_compile import compile_n3_text
if TEXTURE_AVAILABLE:
    from PIL import Image, ImageTk



def blend(a,b,t):
    return tuple(int((1-t)*x+t*y) for x,y in zip(a,b))


def rgbhex(rgb):
    return '#' + ''.join(f'{max(0,min(255,round(v))):02x}' for v in rgb)


def read_pcx_palette(path: Path):
    """Read an indexed VGA 256-color palette from a PCX trailer.

    Reading the original PCX palette does not require decoding its RLE image.
    """
    data=Path(path).read_bytes()
    if (len(data)<897 or data[0]!=10 or data[3]!=8 or data[-769]!=12):
        raise ValueError('Not an 8-bit PCX with a 256-color VGA palette trailer')
    values=data[-768:]
    return [tuple(values[i*3:i*3+3]) for i in range(256)]


def _atomic_write(path: Path, data: bytes):
    """Write through a sibling temporary file so existing files survive errors."""
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_validated_3do(target: Path, data: bytes, *,
                        expected_vertices: int, expected_polygons: int,
                        backup=False):
    """Validate a new 3DO before replacing the target, then back it up.

    The caller handles the confirmation dialogs. If backup=True, the current
    on-disk target bytes (not an old in-memory copy) overwrite `.3do.bak`.
    """
    target=Path(target)
    fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',suffix='.3do',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        candidate=Model(tmp)
        if (len(candidate.polygons)!=expected_polygons or
                len(candidate.vertices)!=expected_vertices):
            raise FormatError('Saved model has different vertex/polygon counts')
        if backup:
            backup_path=target.with_suffix(target.suffix+'.bak')
            _atomic_write(backup_path,target.read_bytes())
        os.replace(tmp,target)
        return Model(target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Editor(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title('ICR2 3DO CAD • Editor v1.9')
        self.geometry('1320x900')
        self.minsize(850,580)
        self.configure(background='#171d29')
        self.model = None
        self.text_document = None  # N3 labels/comments stay in the .3D text, not in a binary 3DO.
        self.imported_pending = False
        self.standalone_n3_binary = None
        self.external_resolver=ExternalResolver()
        self.external_model_cache={}
        self._pmp_cache={}
        self.dynamic_order=[]
        self.selected_dynamic=None
        self.dynamic_info=tk.StringVar(value='No DYNAMIC placements loaded')
        self.dynamic_file_info=tk.StringVar(value='')
        self.dynamic_posvars=[tk.StringVar() for _ in range(3)]
        self.dynamic_rotvars=[tk.StringVar() for _ in range(3)]
        self._screen_dynamics=[]
        self.appearance = None  # Separate 3DO MATERIAL->RECOLOR wrapper, preview-only
        self.appearance_info = tk.StringVar(value="Car appearance: base polygon colors (no RECOLOR file)")
        self.vertex_order = []
        self.selected = None
        self.selected_poly = None
        self.visible_polygon_offsets = set()
        self._screen_polygons = []
        self.poly_order = []
        self.poly_plane_offsets = []
        self.poly_ref_options = []
        self.poly_selected_plane = tk.StringVar(value='')
        self.poly_detail = tk.StringVar(value='Select a polygon to inspect')
        self.poly_color_index=tk.StringVar(value='')
        self.poly_color_explanation=tk.StringVar(value='Select a polygon to edit its original color index.')
        self.poly_color_pair=tk.BooleanVar(value=True)
        self.poly_plane_info = tk.StringVar(value='Select a target FACE/BSP plane')
        self.poly_edit_status = tk.StringVar(value='')
        self.split_edge_a=tk.StringVar(value='')
        self.split_edge_b=tk.StringVar(value='')
        self.split_fraction_a=tk.StringVar(value='0.5')
        self.split_fraction_b=tk.StringVar(value='0.5')
        self.split_hint=tk.StringVar(value='Choose two different edges to split this polygon.')
        self.split_preview=tk.BooleanVar(value=False)
        self.draft_vertices=[]  # stage-only IDs, not saved until used by new polygon
        self.geometry_anchor=tk.StringVar(value='8484')
        self.geometry_insertion=tk.StringVar(value='')
        self.geometry_insertion_targets=[]
        self.geometry_placement=tk.StringVar(value='after')
        self.geometry_two_sided=tk.BooleanVar(value=True)
        self.geometry_textured=tk.BooleanVar(value=False)
        self.geometry_color=tk.StringVar(value='40')
        self.geometry_group=tk.StringVar(value='0')
        self.geometry_points=tk.StringVar(value='')
        self.geometry_xyz=[tk.StringVar(value='0') for _ in range(3)]
        self.geometry_uv=[tk.StringVar(value='0') for _ in range(2)]
        self.geometry_drafts=tk.StringVar(value='No draft vertices (not stored in 3DO until used)')
        self.geometry_status=tk.StringVar(value='Select anchor POLY, LIST insertion point, and ordered vertices.')
        self.geometry_fin_a=tk.StringVar(value='')
        self.geometry_fin_b=tk.StringVar(value='')
        self.geometry_fin_height=tk.StringVar(value='5000')
        self.existing_split_a=tk.StringVar(value='')
        self.existing_split_b=tk.StringVar(value='')
        self.existing_split_preview=tk.BooleanVar(value=True)
        self.existing_split_hint=tk.StringVar(value='Choose two nonadjacent numbered vertices. No new vertices are created.')
        self.poly_ref_selections = [tk.StringVar() for _ in range(3)]
        self.poly_only_visible = tk.BooleanVar(value=False)
        self.poly_vertex_labels = tk.BooleanVar(value=True)
        self.show_hidden_polygon_outline = tk.BooleanVar(value=False)
        self.undo_stack=[]
        self.redo_stack=[]
        self.azimuth = math.radians(35)
        self.elevation = math.radians(25)
        self.zoom = 1.0
        self.pan = (0.0,0.0)
        self.center = (0.0,0.0,0.0)
        self.extent=1.0
        self.scale=1.0
        self.palette=None
        self.palette_source='No palette'
        default_palette=Path(__file__).with_name('gamepal.pcx')
        if default_palette.is_file():
            try:
                self.palette=read_pcx_palette(default_palette)
                self.palette_source=f'Default: {default_palette.name}'
            except (OSError,ValueError):
                self.palette_source='Invalid bundled palette (fallback colors)'
        self.show_textures=tk.BooleanVar(value=True)
        self.texture_repeat=tk.BooleanVar(value=False)
        # Static preview stays detailed; continuous camera/vertex motion uses a
        # cheaper sampling grid, then automatically refines when movement ends.
        self.texture_quality=tk.StringVar(value='Balanced (75%)')
        self._interactive_view=False
        self._pending_view_redraw=None
        self._pending_refine=None
        self.last_render_seconds=0.0
        self.texture_folder=None
        self._mip_path_cache={}  # avoid repeated directory scans for every textured face
        self.texture_manual={}  # ('polygon',offset) or ('group',group): Path
        self.texture_cache={}
        self._texture_photos=[]
        # Keep a bounded cache of static-view tiles: selection/BSP inspector
        # changes no longer force a second UV rasterization of unchanged faces.
        self._texture_tile_cache=OrderedDict()
        self._texture_tile_cache_bytes=0
        self.texture_info=tk.StringVar(value='Texture: select a polygon')
        self.projection=tk.StringVar(value='Orthographic')
        self.lighting=tk.BooleanVar(value=False)
        self.fov_degrees=55.0
        self.show_faces=tk.BooleanVar(value=True)
        self.show_edges=tk.BooleanVar(value=True)
        self.show_points=tk.BooleanVar(value=True)
        self.show_axes=tk.BooleanVar(value=True)
        self.lod_mode=tk.StringVar(value='SWITCH DISTANCE')
        self.lod_distance=tk.DoubleVar(value=0)
        self.lod_distance_text=tk.StringVar(value='0')
        self.bsp_mode=tk.StringVar(value='Original 3DO planes')
        self.preview_stats=tk.StringVar(value='Preview: no model loaded')
        self.active_vertices=set()
        self.axis=tk.StringVar(value='X')
        self.nudge_step=tk.StringVar(value='500')
        self.posvars=[tk.StringVar() for _ in range(3)]
        self.uvvars=[tk.StringVar(),tk.StringVar()]
        self.header=tk.StringVar(value='Open a .3do file to begin')
        self.stats=tk.StringVar(value='3DO body-relative offsets shown throughout')
        self.status=tk.StringVar(value='Click a vertex to select. Right-drag orbit, mouse wheel zoom.')
        self.selection_label=tk.StringVar(value='No vertex selected')
        self.context_title=tk.StringVar(value='Nothing selected')
        self.context_detail=tk.StringVar(value='Open a 3DO to begin.')
        self.unsaved_state=tk.StringVar(value='No edits')
        self.show_header_details=tk.BooleanVar(value=False)
        self.show_view_settings=tk.BooleanVar(value=False)
        self.show_advanced_polygon=tk.BooleanVar(value=False)
        self._model_extent=1.0
        self._drag=None
        self._setup_style()
        self._setup_menu()
        self._build_ui()
        self.protocol('WM_DELETE_WINDOW',self.on_close)
        if path:
            self.after(0,lambda: self.load_file(path))

    def _setup_style(self):
        s=ttk.Style(self)
        if 'clam' in s.theme_names(): s.theme_use('clam')
        s.configure('TFrame',background='#222a38')
        s.configure('TLabel',background='#222a38',foreground='#dce5f1',font=('Segoe UI',10))
        s.configure('Sub.TLabel',background='#222a38',foreground='#96a7bb')
        s.configure('Header.TLabel',background='#222a38',foreground='#f2f7ff',font=('Segoe UI',13,'bold'))
        s.configure('TButton',font=('Segoe UI',10),padding=(8,6))
        s.configure('TEntry',padding=(4,4))
        s.configure('TRadiobutton',background='#222a38',foreground='#dbe5f4')
        s.configure('TCheckbutton',background='#222a38',foreground='#dbe5f4')
        s.map('TCheckbutton',background=[('active','#222a38')])
        s.map('TRadiobutton',background=[('active','#222a38')])

    def _setup_menu(self):
        bar=tk.Menu(self)
        filemenu=tk.Menu(bar,tearoff=0)
        filemenu.add_command(label='Open 3DO…     Ctrl+O',command=self.open_file)
        filemenu.add_command(label='Save As…       Ctrl+Shift+S',command=self.save_as)
        filemenu.add_separator()
        filemenu.add_command(label='Export editable N3 .3D text…',command=self.export_n3_text)
        filemenu.add_command(label='Import N3 .3D onto current 3DO…',command=self.import_n3_text)
        filemenu.add_command(label='Open standalone N3 .3D…',command=self.open_standalone_n3)
        filemenu.add_separator()
        filemenu.add_command(label='Load individual car RECOLOR 3DO…',command=self.open_car_appearance)
        filemenu.add_command(label='Clear individual car RECOLOR preview',command=self.clear_car_appearance)
        filemenu.add_separator()
        filemenu.add_command(label='Open 256-color PCX palette…',command=self.open_palette)
        filemenu.add_command(label='Use bundled gamepal.pcx (default)',command=self.use_default_palette)
        filemenu.add_command(label='Remove palette',command=self.remove_palette)
        filemenu.add_separator()
        filemenu.add_command(label='Choose MIP texture folder…',command=self.choose_texture_folder)
        filemenu.add_command(label='Choose external 3DO folder (wheels, helmet)…',
                             command=self.choose_external_folder)
        filemenu.add_command(label='Assign MIP to selected polygon…',command=self.assign_polygon_texture)
        filemenu.add_command(label='Assign MIP to selected texture group…',command=self.assign_group_texture)
        filemenu.add_command(label='Clear selected texture assignment',command=self.clear_texture_assignment)
        filemenu.add_separator()
        filemenu.add_command(label='Exit' ,command=self.on_close)
        bar.add_cascade(label='File',menu=filemenu)
        edit=tk.Menu(bar,tearoff=0)
        edit.add_command(label='Undo    Ctrl+Z',command=self.undo)
        edit.add_command(label='Redo    Ctrl+Y',command=self.redo)
        edit.add_command(label='Reset all XYZ, UV, plane and DYNAMIC edits',command=self.reset_edits)
        bar.add_cascade(label='Edit',menu=edit)
        view=tk.Menu(bar,tearoff=0)
        for title, var in [('Filled polygons',self.show_faces),('Polygon edges',self.show_edges),
                           ('Vertex dots',self.show_points),('Axes',self.show_axes)]:
            view.add_checkbutton(label=title,variable=var,command=self.redraw)
        view.add_checkbutton(label='Number selected polygon vertices',
                             variable=self.poly_vertex_labels,command=self.redraw)
        view.add_checkbutton(label='Show selected polygon even if BSP-hidden (dashed)',
                             variable=self.show_hidden_polygon_outline,command=self.redraw)
        view.add_separator()
        for option in ('Orthographic','Perspective (depth)'):
            view.add_radiobutton(label=option,variable=self.projection,value=option,
                                 command=self.redraw)
        view.add_checkbutton(label='Lighting (off by default)',variable=self.lighting,
                             command=self.redraw)
        view.add_checkbutton(label='Textured polygons (requires Pillow + NumPy)',
                             variable=self.show_textures, command=self.redraw)
        view.add_checkbutton(label='Repeat UVs outside texture edges (default clamp)',
                             variable=self.texture_repeat,command=self.redraw)
        quality_menu=tk.Menu(view,tearoff=0)
        for quality in ('Fast (50%)','Balanced (75%)','Full (100%)'):
            quality_menu.add_radiobutton(label=quality,variable=self.texture_quality,
                                         value=quality,command=self.redraw)
        view.add_cascade(label='Texture preview quality',menu=quality_menu)
        view.add_separator()
        view.add_radiobutton(label='All LOD branches',variable=self.lod_mode,
                             value='All branches',command=self.redraw)
        view.add_radiobutton(label='Select SWITCH DISTANCE branch',variable=self.lod_mode,
                             value='SWITCH DISTANCE',command=self.redraw)
        view.add_separator()
        for label,value in [('No BSP culling','Off (show all)'),
                            ('BSP from original 3DO','Original 3DO planes'),
                            ('BSP from recalculated planes','Rebuilt planes')]:
            view.add_radiobutton(label=label,variable=self.bsp_mode,value=value,
                                 command=self.redraw)
        view.add_separator()
        view.add_command(label='Frame entire model     F',command=self.frame_model)
        view.add_command(label='Frame selected     Shift+F',command=self.frame_selection)
        camera_menu=tk.Menu(view,tearoff=0)
        for label in ('Three-quarter','Top','Front','Side'):
            camera_menu.add_command(label=label,command=lambda name=label:self.set_camera_view(name))
        view.add_cascade(label='Camera presets',menu=camera_menu)
        view.add_command(label='Polygon editing mode     P',command=lambda:self.notebook.select(self.poly_page))
        view.add_command(label='DYNAMIC component mode',command=lambda:self.notebook.select(self.component_page))
        view.add_command(label='Vertex editing mode       V',command=lambda:self.notebook.select(self.vertex_page))
        view.add_command(label='Plane rebuild report…',command=self.show_report)
        bar.add_cascade(label='View',menu=view)
        helpmenu=tk.Menu(bar,tearoff=0)
        helpmenu.add_command(label='Controls and limitations',command=self.show_help)
        bar.add_cascade(label='Help',menu=helpmenu)
        self.configure(menu=bar)
        self.bind_all('<Control-o>',lambda event: self.open_file())
        self.bind_all('<Control-Shift-S>',lambda event: self.save_as())
        self.bind_all('<Control-z>',lambda event: self.undo())
        self.bind_all('<Control-y>',lambda event: self.redo())
        self.bind_all('<F4>',lambda event: self.show_report())
        self.bind_all('<KeyPress-f>',self._hotkey_frame)
        self.bind_all('<Shift-F>',self._hotkey_frame_selection)
        self.bind_all('<KeyPress-p>',lambda e:self._hotkey_tab(e,self.poly_page))
        self.bind_all('<KeyPress-v>',lambda e:self._hotkey_tab(e,self.vertex_page))

    def _hotkey_frame(self, event):
        if not isinstance(event.widget,(tk.Entry,ttk.Entry)):
            self.frame_model()

    def _hotkey_frame_selection(self,event):
        if not isinstance(event.widget,(tk.Entry,ttk.Entry,ttk.Combobox,tk.Text)):
            self.frame_selection()

    def _toggle_view_settings_from_button(self):
        self.show_view_settings.set(not self.show_view_settings.get())
        self.toggle_view_settings()

    def _toggle_polygon_advanced_from_button(self):
        self.show_advanced_polygon.set(not self.show_advanced_polygon.get())
        self.toggle_polygon_advanced()

    def toggle_header_details(self):
        if self.show_header_details.get():
            self.diagnostics_frame.pack(fill='x',pady=(3,0))
        else:
            self.diagnostics_frame.pack_forget()

    def toggle_view_settings(self):
        if self.show_view_settings.get():
            self.view_options.pack(fill='x',pady=(6,0))
        else:
            self.view_options.pack_forget()

    def toggle_polygon_advanced(self):
        if self.show_advanced_polygon.get():
            self.poly_advanced_container.pack(fill='x',pady=(4,8))
            self.poly_advanced_button.configure(text='Hide advanced splitting / BSP tools')
        else:
            self.poly_advanced_container.pack_forget()
            self.poly_advanced_button.configure(text='Show advanced splitting / BSP tools')

    def _update_selection_summary(self):
        if not hasattr(self,'context_title') or not hasattr(self,'notebook'):
            return
        self.unsaved_state.set('Unsaved changes' if self.model and (self.model.dirty or self.imported_pending) else 'No edits')
        if not self.model:
            label='Nothing selected'
            detail='Open a 3DO model to begin.'
            can_frame=False
        else:
            page=self.notebook.select()
            if page in (str(self.poly_page),str(self.geometry_page)) and self.selected_poly in self.model.polygons:
                poly=self.model.polygons[self.selected_poly]
                label=f'Polygon @{poly.offset}'
                detail=f'{len(poly.unique_refs)} vertices  •  palette {self._color_label(poly)}  •  group {poly.group}'
                can_frame=True
            elif page==str(self.component_page) and self.selected_dynamic in self.model.dynamics:
                part=self.model.dynamics[self.selected_dynamic]
                label=f'Part: {part.name}.3do'
                detail=f'DYNAMIC @{self.selected_dynamic}  •  placement in parent model'
                can_frame=True
            elif page==str(self.vertex_page) and self.selected in self.model.vertices:
                vertex=self.model.vertices[self.selected]
                label=f'Vertex @{self.selected}'
                detail=f'X {vertex.xyz[0]:,}   Y {vertex.xyz[1]:,}   Z {vertex.xyz[2]:,}'
                can_frame=True
            else:
                label='Nothing selected'
                detail='Click a visible element, or select it from the list.'
                can_frame=False
        self.context_title.set(label)
        self.context_detail.set(detail)
        if hasattr(self,'frame_selected_button'):
            self.frame_selected_button.configure(state='normal' if can_frame else 'disabled')
        if hasattr(self,'toolbar_save'):
            self.toolbar_save.configure(state='normal' if self.model else 'disabled')
            self.toolbar_undo.configure(state='normal' if self.undo_stack else 'disabled')
            self.toolbar_redo.configure(state='normal' if self.redo_stack else 'disabled')

    def _hotkey_tab(self,event,page):
        if isinstance(event.widget,(tk.Entry,ttk.Entry,ttk.Combobox,tk.Text)):
            return
        self.notebook.select(page)

    def _build_ui(self):
        top=tk.Frame(self,bg='#151b25',padx=16,pady=10)
        top.pack(side='top',fill='x')
        tk.Label(top,textvariable=self.header,bg='#151b25',fg='#eef5ff',
                 font=('Segoe UI',14,'bold'),anchor='w').pack(anchor='w')
        tk.Checkbutton(top,text='Technical details',variable=self.show_header_details,
                       command=self.toggle_header_details,bg='#151b25',fg='#94a6ba',
                       activebackground='#151b25',activeforeground='#eef5ff',
                       selectcolor='#151b25').pack(anchor='e')
        self.diagnostics_frame=tk.Frame(top,bg='#151b25')
        tk.Label(self.diagnostics_frame,textvariable=self.stats,bg='#151b25',fg='#94a6ba',
                 anchor='w',font=('Segoe UI',9)).pack(anchor='w')
        tk.Label(self.diagnostics_frame,textvariable=self.appearance_info,bg='#151b25',fg='#accfbe',
                 anchor='w',font=('Segoe UI',9)).pack(anchor='w')
        toolbar=tk.Frame(self,bg='#1b2533',padx=10,pady=5)
        toolbar.pack(side='top',fill='x')
        ttk.Button(toolbar,text='Open…',command=self.open_file).pack(side='left',padx=(0,4))
        self.toolbar_save=ttk.Button(toolbar,text='Save Copy…',command=self.save_as)
        self.toolbar_save.pack(side='left',padx=(0,10))
        self.toolbar_undo=ttk.Button(toolbar,text='Undo',command=self.undo)
        self.toolbar_undo.pack(side='left',padx=(0,4))
        self.toolbar_redo=ttk.Button(toolbar,text='Redo',command=self.redo)
        self.toolbar_redo.pack(side='left',padx=(0,10))
        ttk.Label(toolbar,textvariable=self.unsaved_state,style='Sub.TLabel').pack(side='right',padx=6)
        main=tk.PanedWindow(self,orient='horizontal',bg='#10141d',sashwidth=6,
                             borderwidth=0)
        main.pack(expand=True,fill='both')
        self._main_pane=main
        self._initial_panes_job=self.after(180,self._initial_panes)
        left=tk.Frame(main,bg='#131924')
        main.add(left,stretch='always',minsize=480)
        bar=tk.Frame(left,bg='#1b2533',padx=8,pady=4)
        bar.pack(fill='x')
        quick=tk.Frame(bar,bg='#1b2533');quick.pack(fill='x')
        ttk.Label(quick,text='Select:',style='Sub.TLabel').pack(side='left',padx=(0,4))
        for caption,which in (('Vertex','vertex_page'),('Polygon','poly_page'),('Part','component_page')):
            ttk.Button(quick,text=caption,
                       command=lambda name=which:self.notebook.select(getattr(self,name))).pack(side='left',padx=(0,3))
        camera_row=tk.Frame(bar,bg='#1b2533');camera_row.pack(fill='x',pady=(4,0))
        ttk.Label(camera_row,text='View:',style='Sub.TLabel').pack(side='left',padx=(0,4))
        for caption,name in (('3D','Three-quarter'),('Top','Top'),('Front','Front'),('Side','Side')):
            ttk.Button(camera_row,text=caption,
                       command=lambda preset=name:self.set_camera_view(preset)).pack(side='left',padx=(0,2))
        ttk.Button(camera_row,text='Display…',command=self._toggle_view_settings_from_button).pack(side='right')
        framing=tk.Frame(bar,bg='#1b2533');framing.pack(fill='x',pady=(4,0))
        ttk.Button(framing,text='Frame All (F)',command=self.frame_model).pack(side='left',padx=(0,4))
        self.frame_selected_button=ttk.Button(framing,text='Frame Selection (Shift+F)',command=self.frame_selection)
        self.frame_selected_button.pack(side='left')
        self.view_options=tk.Frame(bar,bg='#1b2533')
        line1=tk.Frame(self.view_options,bg='#1b2533');line1.pack(fill='x')
        tk.Label(line1,text='LOD',bg='#1b2533',fg='#c9d8ec').pack(side='left',padx=(0,6))
        self.lod_combo=ttk.Combobox(line1,textvariable=self.lod_mode,
             values=['SWITCH DISTANCE','All branches'],state='readonly',width=19)
        self.lod_combo.pack(side='left')
        self.lod_combo.bind('<<ComboboxSelected>>',lambda e:self.redraw())
        tk.Label(line1,text='BSP preview',bg='#1b2533',fg='#c9d8ec').pack(side='left',padx=(20,6))
        self.bsp_combo=ttk.Combobox(line1,textvariable=self.bsp_mode,
             values=['Off (show all)','Original 3DO planes','Rebuilt planes'],
             state='readonly',width=21)
        self.bsp_combo.pack(side='left')
        self.bsp_combo.bind('<<ComboboxSelected>>',lambda e:self.redraw())
        lineview=tk.Frame(self.view_options,bg='#1b2533');lineview.pack(fill='x',pady=(7,0))
        tk.Label(lineview,text='Projection',bg='#1b2533',fg='#c9d8ec').pack(side='left',padx=(0,6))
        self.projection_combo=ttk.Combobox(lineview,textvariable=self.projection,
            values=['Orthographic','Perspective (depth)'],state='readonly',width=20)
        self.projection_combo.pack(side='left')
        self.projection_combo.bind('<<ComboboxSelected>>',lambda e:self.redraw())
        tk.Checkbutton(lineview,text='Lighting',variable=self.lighting,
            bg='#1b2533',fg='#c9d8ec',selectcolor='#1b2533',
            activebackground='#1b2533',activeforeground='#c9d8ec',
            command=self.redraw).pack(side='left',padx=(16,0))
        tk.Checkbutton(lineview,text='Textures',variable=self.show_textures,
            bg='#1b2533',fg='#c9d8ec',selectcolor='#1b2533',
            activebackground='#1b2533',activeforeground='#c9d8ec',
            command=self.redraw).pack(side='left',padx=(16,0))
        linequality=tk.Frame(self.view_options,bg='#1b2533');linequality.pack(fill='x',pady=(5,0))
        tk.Label(linequality,text='Texture detail',bg='#1b2533',fg='#c9d8ec').pack(side='left',padx=(0,7))
        quality_combo=ttk.Combobox(linequality,textvariable=self.texture_quality,
             values=['Fast (50%)','Balanced (75%)','Full (100%)'],
             state='readonly',width=18)
        quality_combo.pack(side='left')
        quality_combo.bind('<<ComboboxSelected>>',lambda e:self.redraw())
        tk.Label(linequality,text='Motion preview renders faster; refines when idle',
            bg='#1b2533',fg='#91a6bb').pack(side='left',padx=10)
        line2=tk.Frame(self.view_options,bg='#1b2533');line2.pack(fill='x',pady=(7,0))
        tk.Label(line2,text='SWITCH distance (raw units)',bg='#1b2533',fg='#c9d8ec').pack(side='left')
        self.lod_slider=ttk.Scale(line2,from_=0,to=1200000,
             variable=self.lod_distance,command=self._slider_distance)
        self.lod_slider.pack(side='left',fill='x',expand=True,padx=10)
        self.lod_entry=ttk.Entry(line2,textvariable=self.lod_distance_text,width=13)
        self.lod_entry.pack(side='left')
        self.lod_entry.bind('<Return>',self._apply_distance_entry)
        self.lod_entry.bind('<FocusOut>',self._apply_distance_entry)
        tk.Label(self.view_options,textvariable=self.preview_stats,bg='#1b2533',fg='#a9bed5',
                 anchor='w',font=('Consolas',9)).pack(fill='x',pady=(5,0))
        self.canvas=tk.Canvas(left,bg='#131924',highlightthickness=0,confine=True)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e: self.redraw())
        self.canvas.bind('<ButtonPress-1>',self.start_pick)
        self.canvas.bind('<B1-Motion>',self.move_vertex_drag)
        self.canvas.bind('<ButtonRelease-1>',self.finish_vertex_drag)
        self.canvas.bind('<ButtonPress-3>',self.start_orbit)
        self.canvas.bind('<B3-Motion>',self.orbit)
        self.canvas.bind('<ButtonRelease-3>',self.finish_view_motion)
        self.canvas.bind('<ButtonPress-2>',self.start_pan)
        self.canvas.bind('<B2-Motion>',self.pan_view)
        self.canvas.bind('<ButtonRelease-2>',self.finish_view_motion)
        self.canvas.bind('<MouseWheel>',self.wheel_zoom)
        self.canvas.bind('<Button-4>',lambda e: self.wheel_zoom(e,120))
        self.canvas.bind('<Button-5>',lambda e: self.wheel_zoom(e,-120))
        self.canvas.bind('<Double-Button-1>',lambda e:self.frame_model())
        sidebar_shell=tk.Frame(main,bg='#222a38')
        main.add(sidebar_shell,minsize=370,width=410)
        context=tk.Frame(sidebar_shell,bg='#222a38',padx=10,pady=7)
        context.pack(fill='x')
        tk.Label(context,textvariable=self.context_title,bg='#222a38',fg='#f2f7ff',
                 font=('Segoe UI',11,'bold'),anchor='w').pack(anchor='w')
        tk.Label(context,textvariable=self.context_detail,bg='#222a38',fg='#96a7bb',
                 font=('Segoe UI',9),anchor='w',wraplength=370,justify='left').pack(anchor='w')
        self.notebook=ttk.Notebook(sidebar_shell)
        self.notebook.pack(fill='both',expand=True)
        sidebar=tk.Frame(self.notebook,bg='#222a38',padx=12,pady=12)
        self.vertex_page=sidebar
        self.poly_page=tk.Frame(self.notebook,bg='#222a38')
        self.poly_canvas=tk.Canvas(self.poly_page,bg='#222a38',highlightthickness=0)
        self.poly_canvas.pack(side='left',fill='both',expand=True)
        self.poly_scrollbar=ttk.Scrollbar(self.poly_page,orient='vertical',command=self.poly_canvas.yview)
        self.poly_scrollbar.pack(side='right',fill='y')
        self.poly_canvas.configure(yscrollcommand=self.poly_scrollbar.set)
        self.poly_contents=tk.Frame(self.poly_canvas,bg='#222a38',padx=11,pady=10)
        self.poly_canvas_window=self.poly_canvas.create_window((0,0),window=self.poly_contents,anchor='nw')
        self.poly_contents.bind('<Configure>',lambda e:self.poly_canvas.configure(scrollregion=self.poly_canvas.bbox('all')))
        self.poly_canvas.bind('<Configure>',lambda e:self.poly_canvas.itemconfigure(self.poly_canvas_window,width=e.width))
        self.notebook.add(self.vertex_page,text='Vertex')
        self.notebook.add(self.poly_page,text='Polygon')
        self.component_page=tk.Frame(self.notebook,bg='#222a38',padx=10,pady=10)
        self.notebook.add(self.component_page,text='Parts')
        self.geometry_page=tk.Frame(self.notebook,bg='#222a38')
        self.geometry_canvas=tk.Canvas(self.geometry_page,bg='#222a38',highlightthickness=0)
        self.geometry_canvas.pack(side='left',fill='both',expand=True)
        self.geometry_scroll=ttk.Scrollbar(self.geometry_page,orient='vertical',command=self.geometry_canvas.yview)
        self.geometry_scroll.pack(side='right',fill='y')
        self.geometry_canvas.configure(yscrollcommand=self.geometry_scroll.set)
        self.geometry_contents=tk.Frame(self.geometry_canvas,bg='#222a38',padx=11,pady=10)
        self.geometry_window=self.geometry_canvas.create_window((0,0),window=self.geometry_contents,anchor='nw')
        self.geometry_contents.bind('<Configure>',lambda e:self.geometry_canvas.configure(scrollregion=self.geometry_canvas.bbox('all')))
        self.geometry_canvas.bind('<Configure>',lambda e:self.geometry_canvas.itemconfigure(self.geometry_window,width=e.width))
        self.notebook.add(self.geometry_page,text='Create')
        self.raw_page=tk.Frame(self.notebook,bg='#222a38',padx=8,pady=8)
        self.notebook.add(self.raw_page,text='Raw')
        self.notebook.bind('<<NotebookTabChanged>>',lambda e:self._change_edit_mode())
        ttk.Label(sidebar,text='VERTEX EDITOR',style='Header.TLabel').pack(anchor='w')
        ttk.Label(sidebar,textvariable=self.selection_label,style='Sub.TLabel',wraplength=290).pack(anchor='w',pady=(4,12))
        f=ttk.Frame(sidebar)
        f.pack(fill='x')
        for i,name in enumerate('XYZ'):
            ttk.Label(f,text=name,width=3).grid(row=i,column=0,sticky='w',pady=4)
            e=ttk.Entry(f,textvariable=self.posvars[i])
            e.grid(row=i,column=1,sticky='ew',padx=(4,0),pady=4)
            e.bind('<Return>',lambda event:self.apply_coordinates())
        f.columnconfigure(1,weight=1)
        ttk.Button(sidebar,text='Apply coordinates',command=self.apply_coordinates).pack(fill='x',pady=(8,10))
        uv_frame=ttk.Frame(sidebar);uv_frame.pack(fill='x')
        ttk.Label(uv_frame,text='Texture UV (raw uint16)',style='Sub.TLabel').grid(
                 row=0,column=0,columnspan=2,sticky='w',pady=(1,3))
        for i,name in enumerate(('U','V')):
            ttk.Label(uv_frame,text=name,width=3).grid(row=i+1,column=0,sticky='w',pady=2)
            entry=ttk.Entry(uv_frame,textvariable=self.uvvars[i],width=11)
            entry.grid(row=i+1,column=1,sticky='ew',padx=(4,0),pady=2)
            entry.bind('<Return>',lambda e:self.apply_uv())
        uv_frame.columnconfigure(1,weight=1)
        self.uv_apply=ttk.Button(sidebar,text='Apply texture UV',command=self.apply_uv)
        self.uv_apply.pack(fill='x',pady=(5,12))
        ttk.Label(sidebar,text='Mouse drag axis').pack(anchor='w')
        axisrow=ttk.Frame(sidebar);axisrow.pack(fill='x',pady=(4,10))
        for name in 'XYZ':
            ttk.Radiobutton(axisrow,text=name,value=name,variable=self.axis).pack(side='left',padx=(0,20))
        stepframe=ttk.Frame(sidebar);stepframe.pack(fill='x')
        ttk.Label(stepframe,text='Nudge / drag step').pack(side='left')
        ttk.Entry(stepframe,textvariable=self.nudge_step,width=9).pack(side='right')
        nrow=ttk.Frame(sidebar);nrow.pack(fill='x',pady=(8,14))
        ttk.Button(nrow,text='− Step',command=lambda:self.nudge(-1)).pack(side='left',expand=True,fill='x',padx=(0,5))
        ttk.Button(nrow,text='+ Step',command=lambda:self.nudge(1)).pack(side='left',expand=True,fill='x')
        tt=ttk.Frame(sidebar);tt.pack(fill='x')
        ttk.Label(tt,text='Vertices (body offsets)').pack(side='left')
        self.modified_label=tk.Label(tt,text='0 modified',bg='#222a38',fg='#8fa3bb',font=('Segoe UI',9))
        self.modified_label.pack(side='right')
        searchrow=ttk.Frame(sidebar);searchrow.pack(fill='x',pady=(6,5))
        ttk.Label(searchrow,text='Find offset').pack(side='left',padx=(0,8))
        self.offset_entry=ttk.Entry(searchrow,width=13)
        self.offset_entry.pack(side='left',fill='x',expand=True)
        self.offset_entry.bind('<Return>',lambda e:self.find_offset())
        ttk.Button(searchrow,text='Go',command=self.find_offset).pack(side='left',padx=(4,0))
        listframe=ttk.Frame(sidebar);listframe.pack(fill='both',expand=True)
        self.listbox=tk.Listbox(listframe,activestyle='none',font=('Consolas',9),
                                bg='#121924',fg='#bac9dc',selectbackground='#3d77b4',
                                selectforeground='#ffffff',relief='flat',highlightthickness=0,
                                exportselection=False)
        self.listbox.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(listframe,orient='vertical',command=self.listbox.yview)
        scrollbar.pack(side='right',fill='y')
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.bind('<<ListboxSelect>>',self.select_from_list)
        ttk.Button(sidebar,text='Save edited copy…',command=self.save_as).pack(fill='x',pady=(12,5))
        ttk.Button(sidebar,text='View plane rebuild report',command=self.show_report).pack(fill='x')
        self._build_polygon_panel(self.poly_contents)
        self._build_component_panel(self.component_page)
        self._build_geometry_panel(self.geometry_contents)
        self._build_raw_panel(self.raw_page)
        self._bind_polygon_scroll(self.geometry_contents)
        # Wheel events over any polygon inspector control scroll its sidebar;
        # the viewport keeps its own mousewheel zoom behavior.
        self._bind_polygon_scroll(self.poly_contents)
        self._update_selection_summary()
        bottom=tk.Label(self,textvariable=self.status,bg='#151b25',fg='#afc2d8',
                        anchor='w',font=('Segoe UI',9),padx=12,pady=8)
        bottom.pack(side='bottom',fill='x')

    def _initial_panes(self):
        try:
            width=self.winfo_width()
            if width>=1050:
                # Keep the Geometry and Raw tabs accessible at ordinary laptop
                # resolutions, while preserving a resizable viewport.
                self._main_pane.sash_place(0,max(480,width-465),0)
        except tk.TclError:
            pass

    def _build_component_panel(self, sidebar):
        ttk.Label(sidebar,text='DYNAMIC COMPONENTS',style='Header.TLabel').pack(anchor='w')
        ttk.Label(sidebar,text='Referenced 3DOs are loaded read-only. Only placement XYZ and '
                  'Z/Y/X rotations are saved into the currently editable parent 3DO.',
                  style='Sub.TLabel',wraplength=365,justify='left').pack(anchor='w',pady=(5,10))
        ttk.Button(sidebar,text='Choose wheel / external 3DO folder…',
                   command=self.choose_external_folder).pack(fill='x',pady=(0,6))
        ttk.Label(sidebar,textvariable=self.dynamic_file_info,style='Sub.TLabel',
                  wraplength=365,justify='left').pack(anchor='w',pady=(0,8))
        treeframe=ttk.Frame(sidebar);treeframe.pack(fill='both',expand=True)
        self.dynamic_tree=ttk.Treeview(treeframe,columns=('offset','part','edited'),
                      show='headings',height=9,selectmode='browse')
        for key,label,width in [('offset','Offset',80),('part','External 3DO',170),('edited','Edited',65)]:
            self.dynamic_tree.heading(key,text=label)
            self.dynamic_tree.column(key,width=width,anchor='center',stretch=(key=='part'))
        self.dynamic_tree.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(treeframe,orient='vertical',command=self.dynamic_tree.yview)
        scroll.pack(side='right',fill='y')
        self.dynamic_tree.configure(yscrollcommand=scroll.set)
        self.dynamic_tree.bind('<<TreeviewSelect>>',self.select_dynamic_from_list)
        ttk.Label(sidebar,textvariable=self.dynamic_info,style='Sub.TLabel',
                  wraplength=365,justify='left').pack(anchor='w',pady=(10,6))
        xyz=ttk.LabelFrame(sidebar,text='Position • raw 3DO units')
        xyz.pack(fill='x',pady=(2,8))
        for i,axis in enumerate('XYZ'):
            ttk.Label(xyz,text=axis,width=3).grid(row=i,column=0,padx=6,pady=4)
            entry=ttk.Entry(xyz,textvariable=self.dynamic_posvars[i])
            entry.grid(row=i,column=1,sticky='ew',padx=4,pady=3)
            entry.bind('<Return>',lambda event:self.apply_dynamic_transform())
        xyz.columnconfigure(1,weight=1)
        ang=ttk.LabelFrame(sidebar,text='Rotation • degrees')
        ang.pack(fill='x',pady=(0,8))
        for i,axis in enumerate(('Z','Y','X')):
            ttk.Label(ang,text=axis,width=3).grid(row=i,column=0,padx=6,pady=4)
            entry=ttk.Entry(ang,textvariable=self.dynamic_rotvars[i])
            entry.grid(row=i,column=1,sticky='ew',padx=4,pady=3)
            entry.bind('<Return>',lambda event:self.apply_dynamic_transform())
        ang.columnconfigure(1,weight=1)
        ttk.Button(sidebar,text='Apply position and rotation',
                   command=self.apply_dynamic_transform).pack(fill='x',pady=(3,5))
        ttk.Button(sidebar,text='Restore selected placement',
                   command=self.reset_dynamic_transform).pack(fill='x')
        ttk.Label(sidebar,text='Wheel and helmet mesh files are never modified. '
                  'Changing a component transform does not alter its polygons or BSP tree.',
                  style='Sub.TLabel',wraplength=365,justify='left').pack(anchor='w',pady=(12,0))

    def choose_external_folder(self):
        initial=(self.external_resolver.directory or
                 (self.model.path.parent if self.model else Path.cwd()))
        folder=filedialog.askdirectory(title='Folder containing sfront.3do / srear.3do / helmet.3do',
                                       initialdir=str(initial))
        if folder:
            self.external_resolver.choose_directory(folder)
            self.external_model_cache.clear()
            self.refresh_dynamic_list()
            self.redraw()
            self.status.set(f'External 3DO directory: {folder}')

    def refresh_dynamic_list(self):
        if not hasattr(self,'dynamic_tree'):return
        self.dynamic_tree.delete(*self.dynamic_tree.get_children())
        if self.model:
            for ref in sorted(self.model.dynamics):
                placement=self.model.dynamics[ref]
                self.dynamic_tree.insert('','end',iid=str(ref),
                    values=(ref,placement.name+'.3do','Yes' if placement.modified else ''))
        self._update_dynamic_panel()
        if self.selected_dynamic is not None and self.dynamic_tree.exists(str(self.selected_dynamic)):
            self.dynamic_tree.selection_set(str(self.selected_dynamic))
            self.dynamic_tree.see(str(self.selected_dynamic))

    def select_dynamic_from_list(self,event=None):
        selected=self.dynamic_tree.selection()
        if selected:
            ref=int(selected[0])
            if ref!=self.selected_dynamic:
                self.choose_dynamic(ref)

    def choose_dynamic(self,ref):
        if not self.model or ref not in self.model.dynamics:return
        self.selected_dynamic=ref
        if self.dynamic_tree.exists(str(ref)):
            self.dynamic_tree.selection_set(str(ref))
            self.dynamic_tree.see(str(ref))
        self._update_dynamic_panel()
        self.redraw()

    @staticmethod
    def _format_dynamic_angle(raw):
        # Keep the display readable; unchanged entry strings preserve the
        # exact 32-bit source angle when Apply is pressed.
        return f'{papyrus_to_degrees(raw):.5f}'.rstrip('0').rstrip('.')

    def _update_dynamic_panel(self):
        if not self.model:
            self.dynamic_info.set('No 3DO loaded')
            self.dynamic_file_info.set('')
            return
        count=len(self.model.dynamics)
        missing=[]
        for obj in self.model.dynamics.values():
            if self.external_resolver.find(obj.name,self.model.path) is None:
                missing.append(obj.name+'.3do')
        unique_missing=sorted(set(missing))
        self.dynamic_file_info.set(
            f'{count} placements  •  {count-len(missing)} resolved'
            + ('\\nMissing: '+', '.join(unique_missing) if unique_missing else '')
            + ('\\nSearch folder: '+str(self.external_resolver.directory) if self.external_resolver.directory else '')
        )
        obj=self.model.dynamics.get(self.selected_dynamic)
        if not obj:
            self.dynamic_info.set('Select a DYNAMIC record or click its visible component')
            return
        self.dynamic_info.set(f'DYNAMIC @{obj.offset}: {obj.name}.3do'
                    + ('  •  MODIFIED' if obj.modified else ''))
        for i,value in enumerate(obj.xyz):
            self.dynamic_posvars[i].set(str(value))
        for i,raw in enumerate(obj.angles):
            self.dynamic_rotvars[i].set(self._format_dynamic_angle(raw))

    def apply_dynamic_transform(self):
        if not self.model or self.selected_dynamic not in self.model.dynamics:return
        placement=self.model.dynamics[self.selected_dynamic]
        before=(placement.xyz,placement.angles)
        try:
            pos=tuple(int(v.get().strip()) for v in self.dynamic_posvars)
            angles=tuple(
                old if var.get().strip()==self._format_dynamic_angle(old)
                else degrees_to_papyrus(var.get().strip())
                for var,old in zip(self.dynamic_rotvars,placement.angles)
            )
            self.model.set_dynamic(placement.offset,pos,angles)
        except (ValueError,OverflowError) as exc:
            messagebox.showerror('Invalid DYNAMIC transform',
                        'Use whole numbers for XYZ and finite degrees for Z/Y/X.\\n'+str(exc))
            return
        after=(placement.xyz,placement.angles)
        if before!=after:
            self.undo_stack.append(('dynamic',placement.offset,before,after))
            self.redo_stack.clear()
        self.refresh_dynamic_list()
        self.redraw()
        self.status.set(f'DYNAMIC @{placement.offset}: placement updated (external mesh unchanged)')

    def reset_dynamic_transform(self):
        if not self.model or self.selected_dynamic not in self.model.dynamics:return
        obj=self.model.dynamics[self.selected_dynamic]
        before=(obj.xyz,obj.angles)
        after=(obj.original_xyz,obj.original_angles)
        if before!=after:
            self.model.set_dynamic(obj.offset,*after)
            self.undo_stack.append(('dynamic',obj.offset,before,after))
            self.redo_stack.clear()
        self.refresh_dynamic_list()
        self.redraw()

    def _bind_polygon_scroll(self,widget):
        def scroll(event):
            if event.num==4:direction=-1
            elif event.num==5:direction=1
            else:direction=-int(event.delta/120) if event.delta else 0
            if direction:self.poly_canvas.yview_scroll(direction,'units')
            return 'break'
        # Leave Treeview scrolling to its own scroll bindings; users can use
        # the sidebar scrollbar when the pointer is over a list.
        if not isinstance(widget,(ttk.Treeview,ttk.Combobox)):
            widget.bind('<MouseWheel>',scroll)
            widget.bind('<Button-4>',scroll)
            widget.bind('<Button-5>',scroll)
        for ch in widget.winfo_children():
            self._bind_polygon_scroll(ch)

    def _build_polygon_panel(self,sidebar):
        ttk.Label(sidebar,text='POLYGON EDITOR',style='Header.TLabel').pack(anchor='w')
        ttk.Label(sidebar,text='Select a polygon in the viewport or list. Plane edits affect the chosen FACE/BSP record only.',
                  style='Sub.TLabel',wraplength=380).pack(anchor='w',pady=(3,8))
        appearance_buttons=ttk.Frame(sidebar);appearance_buttons.pack(fill='x',pady=(0,7))
        ttk.Button(appearance_buttons,text='Load car RECOLOR 3DO',
                   command=self.open_car_appearance).pack(side='left',fill='x',expand=True,padx=(0,4))
        ttk.Button(appearance_buttons,text='Clear RECOLOR',
                   command=self.clear_car_appearance).pack(side='left')
        bar=ttk.Frame(sidebar);bar.pack(fill='x',pady=(0,5))
        ttk.Label(bar,text='Find poly offset').pack(side='left')
        self.poly_find_entry=ttk.Entry(bar,width=12)
        self.poly_find_entry.pack(side='left',fill='x',expand=True,padx=(6,4))
        self.poly_find_entry.bind('<Return>',lambda e:self.find_polygon())
        ttk.Button(bar,text='Go',command=self.find_polygon).pack(side='left')
        ttk.Checkbutton(sidebar,text='List only polygons in active LOD/BSP preview',
                        variable=self.poly_only_visible,command=self.refresh_polygon_list).pack(anchor='w',pady=(0,5))
        polyframe=ttk.Frame(sidebar);polyframe.pack(fill='x',expand=False)
        self.poly_tree=ttk.Treeview(polyframe,columns=('offset','type','verts','color'),
                                    show='headings',selectmode='browse',height=4)
        for key,label,width in [('offset','Offset',78),('type','Type',90),
                                ('verts','Verts',52),('color','Color / RECOLOR',114)]:
            self.poly_tree.heading(key,text=label)
            self.poly_tree.column(key,width=width,stretch=(key=='type'),anchor='center')
        self.poly_tree.pack(side='left',fill='both',expand=True)
        sc=ttk.Scrollbar(polyframe,orient='vertical',command=self.poly_tree.yview)
        sc.pack(side='right',fill='y')
        self.poly_tree.configure(yscrollcommand=sc.set)
        self.poly_tree.bind('<<TreeviewSelect>>',self.select_polygon_from_list)
        ttk.Label(sidebar,textvariable=self.poly_detail,style='Sub.TLabel',
                  wraplength=385).pack(anchor='w',pady=(8,4))
        # A real POLY record stores a signed 32-bit field used as a palette slot.
        # Keep this separate from the individual-car RECOLOR preview wrapper.
        colorbox=ttk.LabelFrame(sidebar,text='Polygon color (editable)')
        colorbox.pack(fill='x',pady=(5,8))
        cbar=ttk.Frame(colorbox);cbar.pack(fill='x',padx=6,pady=(5,2))
        ttk.Label(cbar,text='Base palette index (0–255)').pack(side='left')
        self.poly_color_entry=ttk.Entry(cbar,textvariable=self.poly_color_index,width=6)
        self.poly_color_entry.pack(side='left',padx=(7,4))
        self.poly_color_entry.bind('<Return>',lambda e:self.apply_polygon_color())
        ttk.Button(cbar,text='Palette…',command=self.choose_polygon_palette_color).pack(side='left',padx=(0,4))
        ttk.Button(cbar,text='Apply',command=self.apply_polygon_color).pack(side='left')
        self.poly_color_swatch=tk.Label(cbar,width=4,height=1,relief='solid',bg='#414a5b')
        self.poly_color_swatch.pack(side='right',padx=(4,0))
        ttk.Checkbutton(colorbox,text='Also update opposite FACE2 side (if present)',
                        variable=self.poly_color_pair).pack(anchor='w',padx=6,pady=2)
        ttk.Label(colorbox,textvariable=self.poly_color_explanation,style='Sub.TLabel',
                  wraplength=365,justify='left').pack(anchor='w',padx=6,pady=(2,6))
        ttk.Checkbutton(sidebar,text='Show numbered vertices on selected polygon',
                        variable=self.poly_vertex_labels,command=self.redraw).pack(anchor='w',pady=(2,2))
        ttk.Checkbutton(sidebar,text='Show ghost outline when BSP-hidden',
                        variable=self.show_hidden_polygon_outline,command=self.redraw).pack(anchor='w',pady=(0,5))
        ttk.Label(sidebar,text='Polygon texture (UVs in texel units)',style='TLabel').pack(anchor='w',pady=(4,0))
        ttk.Label(sidebar,textvariable=self.texture_info,style='Sub.TLabel',
                  wraplength=385).pack(anchor='w',pady=(2,3))
        texbuttons=ttk.Frame(sidebar);texbuttons.pack(fill='x',pady=(0,7))
        ttk.Button(texbuttons,text='Assign polygon MIP',command=self.assign_polygon_texture).pack(
                   side='left',padx=(0,3))
        ttk.Button(texbuttons,text='Assign group MIP',command=self.assign_group_texture).pack(
                   side='left',padx=(0,3))
        ttk.Button(texbuttons,text='Clear',command=self.clear_texture_assignment).pack(side='left')
        ttk.Label(sidebar,text='Polygon vertices (ordered)',style='TLabel').pack(anchor='w')
        vframe=ttk.Frame(sidebar);vframe.pack(fill='x',expand=False,pady=(4,7))
        self.poly_vertex_tree=ttk.Treeview(vframe,columns=('idx','offset','xyz','uv'),
                    show='headings',selectmode='browse',height=4)
        for key,label,width in [('idx','#',30),('offset','Offset',70),
                                ('xyz','X, Y, Z',185),('uv','U, V',95)]:
            self.poly_vertex_tree.heading(key,text=label)
            self.poly_vertex_tree.column(key,width=width,stretch=(key=='xyz'),anchor='w')
        self.poly_vertex_tree.pack(side='left',fill='both',expand=True)
        sc2=ttk.Scrollbar(vframe,orient='vertical',command=self.poly_vertex_tree.yview)
        sc2.pack(side='right',fill='y')
        self.poly_vertex_tree.configure(yscrollcommand=sc2.set)
        self.poly_vertex_tree.bind('<Double-1>',self._open_vertex_from_polygon)
        self.poly_advanced_button=ttk.Button(sidebar,text='Show advanced splitting / BSP tools',
                                              command=self._toggle_polygon_advanced_from_button)
        self.poly_advanced_button.pack(fill='x',pady=(5,6))
        self.poly_advanced_container=tk.Frame(sidebar,bg='#222a38')
        advanced=self.poly_advanced_container
        # Split already-established polygon vertices, no new vertex records.
        existingframe=ttk.LabelFrame(advanced,text='Split between existing vertices (no new vertices)')
        existingframe.pack(fill='x',pady=(6,8))
        ttk.Label(existingframe,text='Choose two nonadjacent numbered vertices; cut follows their diagonal.',
                  style='Sub.TLabel',wraplength=360).pack(anchor='w',padx=5,pady=(4,4))
        pickrow=ttk.Frame(existingframe);pickrow.pack(fill='x',padx=5,pady=2)
        self.existing_split_combos=[]
        for label,variable in (('Vertex A',self.existing_split_a),('Vertex B',self.existing_split_b)):
            ttk.Label(pickrow,text=label).pack(side='left',padx=(0,3))
            combo=ttk.Combobox(pickrow,textvariable=variable,state='readonly',width=11)
            combo.pack(side='left',fill='x',expand=True,padx=(0,8))
            combo.bind('<<ComboboxSelected>>',lambda e:self.redraw())
            self.existing_split_combos.append(combo)
        ttk.Checkbutton(existingframe,text='Preview existing-vertex diagonal',
                        variable=self.existing_split_preview,command=self.redraw).pack(
                        anchor='w',padx=5,pady=3)
        ttk.Button(existingframe,text='Split using existing vertices',
                   command=self.commit_existing_vertex_split).pack(fill='x',padx=5,pady=4)
        ttk.Label(existingframe,textvariable=self.existing_split_hint,style='Sub.TLabel',
                  wraplength=365,justify='left').pack(anchor='w',padx=5,pady=(0,4))
        # Split tool: cut from an interpolated point on each selected edge.
        splitframe=ttk.LabelFrame(advanced,text='Split selected polygon (adds vertices)')
        splitframe.pack(fill='x',pady=(6,10))
        ttk.Label(splitframe,text='Edge #n means vertex #n → next vertex.',
                  style='Sub.TLabel',wraplength=310).pack(anchor='w',padx=5,pady=(4,4))
        self.split_edge_combos=[]
        for label,selector,fraction in [('Edge A',self.split_edge_a,self.split_fraction_a),
                                        ('Edge B',self.split_edge_b,self.split_fraction_b)]:
            line=ttk.Frame(splitframe);line.pack(fill='x',padx=5,pady=2)
            ttk.Label(line,text=label,width=7).pack(side='left')
            combo=ttk.Combobox(line,textvariable=selector,state='readonly',width=15)
            combo.pack(side='left',padx=(1,4))
            combo.bind('<<ComboboxSelected>>',lambda e:self.redraw())
            self.split_edge_combos.append(combo)
            ttk.Label(line,text='t').pack(side='left')
            entry=ttk.Entry(line,textvariable=fraction,width=5)
            entry.pack(side='left',padx=(3,0))
            entry.bind('<Return>',lambda e:self.redraw())
            entry.bind('<FocusOut>',lambda e:self.redraw())
        ttk.Checkbutton(splitframe,text='Show proposed cut in preview',variable=self.split_preview,
                        command=self.redraw).pack(anchor='w',padx=5,pady=3)
        ttk.Button(splitframe,text='Split polygon (append + repoint)',
                   command=self.commit_polygon_split).pack(fill='x',padx=5,pady=5)
        ttk.Label(splitframe,textvariable=self.split_hint,style='Sub.TLabel',
                  wraplength=375,justify='left').pack(anchor='w',padx=5,pady=(0,4))
        ttk.Label(advanced,text='Target FACE/BSP plane',style='TLabel').pack(anchor='w')
        self.poly_plane_combo=ttk.Combobox(advanced,textvariable=self.poly_selected_plane,
                                            state='readonly',width=35)
        self.poly_plane_combo.pack(fill='x',pady=(4,3))
        self.poly_plane_combo.bind('<<ComboboxSelected>>',lambda e:self.update_poly_plane_panel())
        ttk.Label(advanced,textvariable=self.poly_plane_info,style='Sub.TLabel',
                  wraplength=385,justify='left').pack(anchor='w',pady=(2,7))
        ttk.Label(advanced,text='Planes may intentionally be noncoplanar with the polygon. '
                                'Choose any 3 distinct, noncollinear vertices; the maximum '
                                'deviation is shown as a diagnostic, not a restriction.',
                  style='Sub.TLabel',wraplength=385,justify='left').pack(anchor='w',pady=(0,7))
        ttk.Label(advanced,text='Manual plane: 3 ordered vertices (P1 → P2 → P3)',
                  style='TLabel').pack(anchor='w')
        triplet=ttk.Frame(advanced);triplet.pack(fill='x',pady=(4,7))
        self.poly_ref_combos=[]
        for i,label in enumerate(('P1','P2','P3')):
            frm=ttk.Frame(triplet);frm.pack(side='left',fill='x',expand=True,padx=(0,3))
            ttk.Label(frm,text=label,style='Sub.TLabel').pack(anchor='w')
            cmb=ttk.Combobox(frm,textvariable=self.poly_ref_selections[i],
                             width=12,state='readonly')
            cmb.pack(fill='x')
            self.poly_ref_combos.append(cmb)
        actions=ttk.Frame(advanced);actions.pack(fill='x')
        ttk.Button(actions,text='Auto calculate',command=self.auto_polygon_plane).pack(
                   side='left',fill='x',expand=True,padx=(0,3))
        ttk.Button(actions,text='Use P1/P2/P3',command=self.manual_polygon_plane).pack(
                   side='left',fill='x',expand=True)
        actions2=ttk.Frame(advanced);actions2.pack(fill='x',pady=(5,0))
        ttk.Button(actions2,text='Flip plane orientation',command=self.flip_polygon_plane).pack(
                   side='left',fill='x',expand=True,padx=(0,3))
        ttk.Button(actions2,text='Clear override',command=self.clear_polygon_plane).pack(
                   side='left',fill='x',expand=True)
        ttk.Label(advanced,textvariable=self.poly_edit_status,style='Sub.TLabel',
                  wraplength=385,justify='left').pack(anchor='w',pady=(6,7))


    def _build_geometry_panel(self, frame):
        ttk.Label(frame,text='ADD GEOMETRY',style='Header.TLabel').pack(anchor='w')
        ttk.Label(frame,text='All new surfaces are appended, then inserted through ONE chosen parent LIST link. '
                  'Original BSP tree, geometry, and other LOD pointers remain byte-identical.',
                  style='Sub.TLabel',wraplength=370,justify='left').pack(anchor='w',pady=(4,10))
        first=ttk.LabelFrame(frame,text='1. Anchor and paint-order placement')
        first.pack(fill='x',pady=(0,8))
        row=ttk.Frame(first);row.pack(fill='x',padx=6,pady=5)
        ttk.Label(row,text='Anchor POLY @').pack(side='left')
        ttk.Entry(row,textvariable=self.geometry_anchor,width=12).pack(side='left',padx=(4,5))
        ttk.Button(row,text='Find LIST links',command=self.refresh_geometry_targets).pack(side='left')
        ttk.Label(first,text='Choose the parent link; one path is repointed, not every use of the LIST.',
                  style='Sub.TLabel',wraplength=350).pack(anchor='w',padx=6)
        self.geometry_target_combo=ttk.Combobox(first,textvariable=self.geometry_insertion,
                                                width=42,state='readonly')
        self.geometry_target_combo.pack(fill='x',padx=6,pady=5)
        for txt,value in [('Paint BEFORE anchor child','before'),('Paint AFTER anchor child','after')]:
            ttk.Radiobutton(first,text=txt,value=value,
                           variable=self.geometry_placement).pack(anchor='w',padx=6,pady=2)
        ttk.Label(first,text='Fixed LIST paint order is NOT automatic near/far BSP sorting. '
                  'Test multiple camera directions and adjust this placement as needed.',
                  style='Sub.TLabel',wraplength=360).pack(anchor='w',padx=6,pady=(3,7))
        second=ttk.LabelFrame(frame,text='2. Stage a free vertex (optional)')
        second.pack(fill='x',pady=6)
        ttk.Label(second,text='Drafts live only in memory until included in a created polygon.',
                  style='Sub.TLabel',wraplength=345).pack(anchor='w',padx=6,pady=4)
        fields=ttk.Frame(second);fields.pack(fill='x',padx=6)
        for i,axis in enumerate(('X','Y','Z')):
            ttk.Label(fields,text=axis).grid(row=i,column=0,sticky='w')
            ttk.Entry(fields,textvariable=self.geometry_xyz[i],width=19).grid(row=i,column=1,sticky='ew',padx=5,pady=2)
        for i,axis in enumerate(('U','V')):
            ttk.Label(fields,text=axis).grid(row=i,column=2,sticky='w',padx=(10,0))
            ttk.Entry(fields,textvariable=self.geometry_uv[i],width=8).grid(row=i,column=3,sticky='ew',padx=5,pady=2)
        ttk.Button(second,text='Stage vertex as V1, V2, …',command=self.stage_geometry_vertex).pack(fill='x',padx=6,pady=5)
        ttk.Label(second,textvariable=self.geometry_drafts,style='Sub.TLabel',wraplength=355).pack(anchor='w',padx=6)
        ttk.Button(second,text='Clear unused drafts',command=self.clear_geometry_drafts).pack(fill='x',padx=6,pady=(4,6))
        third=ttk.LabelFrame(frame,text='3. Create polygon')
        third.pack(fill='x',pady=7)
        ttk.Label(third,text='Ordered points: existing offsets like @1234, draft IDs like V1, '
                  'or inline XYZ coordinates like (100,0,500). Separate with semicolons.',
                  style='Sub.TLabel',wraplength=345).pack(anchor='w',padx=6,pady=(5,4))
        entry=ttk.Entry(third,textvariable=self.geometry_points)
        entry.pack(fill='x',padx=6,pady=(0,6))
        ttk.Checkbutton(third,text='Two-sided (FACE2 + reversed rear polygon)',
                        variable=self.geometry_two_sided).pack(anchor='w',padx=6,pady=2)
        ttk.Checkbutton(third,text='Textured POLY [T] (all vertices need U/V)',
                        variable=self.geometry_textured).pack(anchor='w',padx=6,pady=2)
        row=ttk.Frame(third);row.pack(fill='x',padx=6,pady=5)
        ttk.Label(row,text='Color').pack(side='left')
        ttk.Entry(row,textvariable=self.geometry_color,width=9).pack(side='left',padx=(4,13))
        ttk.Label(row,text='Texture group').pack(side='left')
        ttk.Entry(row,textvariable=self.geometry_group,width=9).pack(side='left',padx=4)
        ttk.Button(third,text='Create polygon (append + repoint)',
                   command=self.create_geometry_polygon).pack(fill='x',padx=6,pady=(2,8))
        fin=ttk.LabelFrame(frame,text='Quick tool: upright triangular fin')
        fin.pack(fill='x',pady=7)
        ttk.Label(fin,text='Uses two existing vertices on the anchor polygon, '
                  'plus one new apex elevated in +Z.',style='Sub.TLabel',wraplength=350).pack(anchor='w',padx=6,pady=5)
        row=ttk.Frame(fin);row.pack(fill='x',padx=6)
        ttk.Label(row,text='Base A').pack(side='left')
        self.fin_base_a=ttk.Combobox(row,textvariable=self.geometry_fin_a,state='readonly',width=9)
        self.fin_base_a.pack(side='left',padx=(3,5))
        ttk.Label(row,text='Base B').pack(side='left')
        self.fin_base_b=ttk.Combobox(row,textvariable=self.geometry_fin_b,state='readonly',width=9)
        self.fin_base_b.pack(side='left',padx=(3,0))
        row=ttk.Frame(fin);row.pack(fill='x',padx=6,pady=5)
        ttk.Label(row,text='Apex height (+Z)').pack(side='left')
        ttk.Entry(row,textvariable=self.geometry_fin_height,width=14).pack(side='left',padx=5)
        ttk.Button(fin,text='Create fin using anchor edge',command=self.create_geometry_fin).pack(
                   fill='x',padx=6,pady=(2,7))
        ttk.Label(frame,textvariable=self.geometry_status,style='Sub.TLabel',wraplength=365,
                  justify='left').pack(anchor='w',pady=6)

    def _build_raw_panel(self, frame):
        ttk.Label(frame,text='3DO DISASSEMBLY  •  READ ONLY',style='Header.TLabel').pack(anchor='w')
        ttk.Label(frame,text='Body-relative offsets; retained pointers, FACE/BSP equations, '
                  'LIST order, switches, vertices and external models.',style='Sub.TLabel',
                  wraplength=365).pack(anchor='w',pady=5)
        row=ttk.Frame(frame);row.pack(fill='x',pady=5)
        self.raw_find=tk.StringVar(value='')
        ttk.Entry(row,textvariable=self.raw_find,width=14).pack(side='left')
        ttk.Button(row,text='Jump to @offset',command=self.raw_jump).pack(side='left',padx=5)
        ttk.Button(row,text='Refresh',command=self.refresh_raw).pack(side='left')
        rawframe=ttk.Frame(frame);rawframe.pack(fill='both',expand=True)
        self.raw_text=tk.Text(rawframe,wrap='none',font=('Consolas',9),
                             bg='#131924',fg='#c6d7e9',insertbackground='#fff',
                             borderwidth=0,highlightthickness=0)
        self.raw_text.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(rawframe,command=self.raw_text.yview)
        scroll.pack(side='right',fill='y');self.raw_text.configure(yscrollcommand=scroll.set)
        self.raw_text.configure(state='disabled')

    def refresh_raw(self):
        from raw_disassembly import disassemble
        self.raw_text.configure(state='normal')
        self.raw_text.delete('1.0','end')
        if self.model:self.raw_text.insert('1.0',disassemble(self.model))
        self.raw_text.configure(state='disabled')

    def raw_jump(self):
        try:target=int(self.raw_find.get().strip().lstrip('@'),0)
        except ValueError:
            try:target=int(self.raw_find.get().strip().lstrip('@'))
            except ValueError:return
        text=self.raw_text.get('1.0','end')
        for i,line in enumerate(text.splitlines(),1):
            if line.startswith(f'@{target:<7} '):
                self.raw_text.see(f'{i}.0')
                self.raw_text.tag_remove('sel','1.0','end')
                self.raw_text.tag_add('sel',f'{i}.0',f'{i}.end')
                break

    def stage_geometry_vertex(self):
        try:
            xyz=tuple(int(v.get()) for v in self.geometry_xyz)
            uv=tuple(int(v.get()) for v in self.geometry_uv)
            if any(not -(1<<31)<=v<(1<<31) for v in xyz) or any(not 0<=v<65536 for v in uv):
                raise ValueError('XYZ must be int32, U/V must be uint16')
        except ValueError as e:
            messagebox.showerror('Invalid draft vertex',str(e));return
        self.draft_vertices.append((*xyz,*uv))
        self.geometry_drafts.set('  '.join(f'V{i+1}=<{p[0]},{p[1]},{p[2]}>'
                              for i,p in enumerate(self.draft_vertices)))
        self.geometry_status.set(f'Added draft V{len(self.draft_vertices)}. Reference it in ordered polygon points.')
        self.redraw()

    def clear_geometry_drafts(self):
        self.draft_vertices=[]
        self.geometry_drafts.set('No draft vertices (not stored in 3DO until used)')
        self.redraw()

    def refresh_geometry_targets(self):
        from geometry_add import list_insert_targets
        if not self.model:return
        try:anchor=int(self.geometry_anchor.get().strip().lstrip('@'))
        except ValueError:
            self.geometry_status.set('Enter an existing POLY body offset.');return
        targets=list_insert_targets(self.model,anchor)
        self.geometry_insertion_targets=targets
        names=[]
        for list_off,child_idx,parent,slot in targets:
            child=self.model.children[list_off][child_idx]
            names.append(f'LIST @{list_off} child @{child} → '
                         + (f'parent @{parent} slot @{slot}' if parent>=0 else 'ROOT'))
        self.geometry_target_combo.configure(values=names)
        if names:self.geometry_insertion.set(names[0])
        else:self.geometry_insertion.set('')
        self.geometry_status.set(f'{len(targets)} valid insertion occurrence(s) for POLY @{anchor}. '
                                 'Choose one occurrence to avoid affecting unrelated branches.')
        vals=[f'#{j+1} @{v}' for j,v in enumerate(self.model.polygons[anchor].refs)] if anchor in self.model.polygons else []
        self.fin_base_a.configure(values=vals)
        self.fin_base_b.configure(values=vals)
        if vals:self.geometry_fin_a.set(vals[0])
        if len(vals)>1:self.geometry_fin_b.set(vals[1])

    def _geometry_vertex_specs(self):
        import re
        items=[p.strip() for p in self.geometry_points.get().split(';') if p.strip()]
        specs=[]
        for item in items:
            if item.startswith('@'):
                specs.append(int(item[1:]))
            elif re.fullmatch(r'V\d+',item,re.IGNORECASE):
                k=int(item[1:])-1
                if not 0<=k<len(self.draft_vertices):
                    raise ValueError(f'Draft vertex {item} does not exist')
                xyzuv=self.draft_vertices[k]
                specs.append(xyzuv if self.geometry_textured.get() else xyzuv[:3])
            else:
                nums=[int(v.strip()) for v in item.strip('()[]<>').split(',')]
                specs.append(tuple(nums))
        return specs

    def _commit_new_geometry(self,specs):
        from geometry_add import create_model_polygon
        from three_do import FormatError
        if not self.model:return
        try:
            index=self.geometry_target_combo.current()
            if not 0<=index<len(self.geometry_insertion_targets):
                raise ValueError('Choose a LIST insertion occurrence')
            anchor=int(self.geometry_anchor.get().strip().lstrip('@'))
            target=self.geometry_insertion_targets[index]
            updated,result=create_model_polygon(self.model,anchor,*target,specs,
                color=int(self.geometry_color.get()),group=int(self.geometry_group.get()),
                textured=self.geometry_textured.get(),two_sided=self.geometry_two_sided.get(),
                after=self.geometry_placement.get()=='after')
        except (ValueError,FormatError,OverflowError,IndexError) as e:
            messagebox.showerror('Cannot add geometry',str(e));return
        details=(f'Add {len(result.new_vertices)} vertices, {len(result.new_polygons)} polygon(s), '
                 f'FACE @ {result.face_offset}, LIST @ {result.replacement_list}.\n\n'
                 f'Repoint only parent slot @{result.patched_slot}.\n\n'
                 'Existing geometry remains in place; fixed LIST ordering may cause occlusion errors. '
                 'Test multiple views in-game.')
        if not messagebox.askyesno('Commit geometry?',details):return
        before=self.model
        self.undo_stack.append(('topology',before,updated));self.redo_stack.clear()
        self._sync_topology_model(updated,result.new_polygons[0])
        self.draft_vertices=[]
        self.geometry_drafts.set('No draft vertices (not stored in 3DO until used)')
        self.geometry_status.set(f'Created FACE @{result.face_offset}, '
            f'POLY @{result.new_polygons[0]} with {len(result.new_vertices)} new vertices. '
            'Saved only when you save the parent 3DO.')
        self.refresh_geometry_targets()
        self.refresh_raw()

    def create_geometry_polygon(self):
        try:specs=self._geometry_vertex_specs()
        except (ValueError,IndexError) as e:
            messagebox.showerror('Invalid polygon points',str(e));return
        self._commit_new_geometry(specs)

    def create_geometry_fin(self):
        if not self.model:return
        try:
            anchor=int(self.geometry_anchor.get().strip().lstrip('@'))
            refs=self.model.polygons[anchor].refs
            a=int(self.geometry_fin_a.get().split()[0].lstrip('#'))-1
            b=int(self.geometry_fin_b.get().split()[0].lstrip('#'))-1
            if a==b:raise ValueError('Choose two different base vertices')
            pa=self.model.vertices[refs[a]].xyz
            pb=self.model.vertices[refs[b]].xyz
            height=int(self.geometry_fin_height.get())
            if height==0:raise ValueError('Apex height cannot be zero')
            apex=(round((pa[0]+pb[0])/2),round((pa[1]+pb[1])/2),
                  round((pa[2]+pb[2])/2)+height)
            self.geometry_textured.set(False)
        except (ValueError,KeyError,IndexError) as e:
            messagebox.showerror('Invalid fin base',str(e));return
        self._commit_new_geometry([refs[a],refs[b],apex])

    def _change_edit_mode(self):
        if self.model and self.notebook.select()==str(self.geometry_page):
            if self.selected_poly in self.model.polygons:
                self.geometry_anchor.set(str(self.selected_poly))
                self.refresh_geometry_targets()
        if self.model and self.notebook.select()==str(self.raw_page):
            self.refresh_raw()
        if self.model:
            self.redraw()
        page=self.notebook.select()
        if page==str(self.poly_page):
            self.status.set('Polygon mode: click a visible parent polygon. External parts are read-only.')
        elif page==str(self.component_page):
            self.status.set('Components: click a wheel/helmet in the viewport or use the list; edit XYZ and rotation here.')
        else:
            self.status.set('Vertex mode: left-click a parent vertex and drag it along the chosen axis.')

    def refresh_polygon_list(self):
        if not hasattr(self,'poly_tree'):
            return
        previously=self.selected_poly
        self.poly_tree.delete(*self.poly_tree.get_children())
        if self.model:
            for off in self.poly_order:
                if self.poly_only_visible.get() and off not in self.visible_polygon_offsets:
                    continue
                poly=self.model.polygons[off]
                kind='POLY [T]' if poly.kind==2 else 'POLY'
                self.poly_tree.insert('', 'end',iid=str(off),values=(off,kind,
                                       len(poly.unique_refs),self._color_label(poly)))
        if previously is not None and self.poly_tree.exists(str(previously)):
            self.poly_tree.selection_set(str(previously))
            self.poly_tree.see(str(previously))

    def choose_polygon(self,off):
        if not self.model or off not in self.model.polygons:
            return
        self.selected_poly=off
        if self.poly_tree.exists(str(off)):
            self.poly_tree.selection_set(str(off))
            self.poly_tree.see(str(off))
        self._refresh_polygon_inspector()
        self.redraw()

    def select_polygon_from_list(self,event=None):
        if not self.model:
            return
        selected=self.poly_tree.selection()
        if selected:
            off=int(selected[0])
            if off!=self.selected_poly:
                self.selected_poly=off
                self._refresh_polygon_inspector()
                self.redraw()

    def find_polygon(self):
        if not self.model:return
        try:
            word=self.poly_find_entry.get().strip().lower()
            off=int(word,16) if word.startswith('0x') else int(word)
            if off not in self.model.polygons:
                messagebox.showinfo('Polygon not found',f'No polygon at body offset {off}.')
                return
            self.choose_polygon(off)
        except ValueError:
            messagebox.showwarning('Invalid offset','Use a decimal or 0x hexadecimal 3DO body offset.')

    def _open_vertex_from_polygon(self,event=None):
        selected=self.poly_vertex_tree.selection()
        if selected and self.model:
            idx=int(selected[0])
            refs=self.model.polygons[self.selected_poly].refs
            self.notebook.select(self.vertex_page)
            self.choose(refs[idx])

    def _refresh_polygon_inspector(self):
        self._refresh_texture_info()
        self.poly_vertex_tree.delete(*self.poly_vertex_tree.get_children())
        self.poly_plane_offsets=[]
        self.poly_plane_combo.configure(values=[])
        self.poly_selected_plane.set('')
        self.poly_ref_options=[]
        for selection,combo in zip(self.poly_ref_selections,self.poly_ref_combos):
            selection.set('');combo.configure(values=[])
        if self.model is None or self.selected_poly is None:
            self.poly_detail.set('Select a polygon to inspect')
            self._refresh_poly_color_control()
            self.poly_plane_info.set('No plane selected')
            return
        poly=self.model.polygons[self.selected_poly]
        present=self.selected_poly in self.visible_polygon_offsets
        mode=('VISIBLE' if present else ('HIDDEN (ghost outline enabled)' if self.show_hidden_polygon_outline.get()
                                        else 'HIDDEN by current LOD/BSP preview'))
        self._refresh_poly_color_control()
        self.poly_detail.set(f'POLY @{poly.offset}  •  {len(poly.unique_refs)} unique vertices  •  '
                             f'Color {self._color_label(poly)}  •  Group {poly.group}  •  {mode}')
        edge_options=[f'{j+1}: #{j+1} → #{(j+1)%len(poly.refs)+1}'
                      for j in range(len(poly.refs))]
        vertex_choices=[f'#{j+1}' for j,ref in enumerate(poly.refs)]
        for combo in self.existing_split_combos:
            combo.configure(values=vertex_choices)
        self.existing_split_a.set(vertex_choices[0] if len(vertex_choices)>=4 else '')
        self.existing_split_b.set(vertex_choices[2] if len(vertex_choices)>=4 else '')
        for combo in self.split_edge_combos:combo.configure(values=edge_options)
        self.split_edge_a.set(edge_options[0] if edge_options else '')
        self.split_edge_b.set(edge_options[min(2,len(edge_options)-1)] if edge_options else '')
        for ix,ref in enumerate(poly.refs):
            vert=self.model.vertices[ref]
            xyz=', '.join(map(str,vert.xyz))
            uv=(', '.join(map(str,vert.uv)) if vert.uv is not None else '—')
            self.poly_vertex_tree.insert('', 'end',iid=str(ix),values=(ix+1,ref,xyz,uv))
        options=[f'{i+1}: {r}' for i,r in enumerate(poly.unique_refs)]
        self.poly_ref_options=list(poly.unique_refs)
        best=polygon_triplet_refs(poly,self.model.vertices)
        for j,comb in enumerate(self.poly_ref_combos):
            comb.configure(values=options)
            if best and j<len(best):
                choice=options[self.poly_ref_options.index(best[j])]
                self.poly_ref_selections[j].set(choice)
            elif j<len(options):
                self.poly_ref_selections[j].set(options[j])
        self.poly_plane_offsets=self.model.planes_for_polygon(poly.offset)
        labels=[]
        for off in self.poly_plane_offsets:
            plane=self.model.planes[off]
            rel=self.model.plane_relationship(poly.offset,off)
            mark='*' if off in self.model.plane_edits else ' '
            labels.append(f'{mark} {NAMES[plane.kind]} @{off}  [{rel}]')
        self.poly_plane_combo.configure(values=labels)
        if labels:
            # Prefer an already customized target, otherwise the first
            # verified local match, otherwise the closest candidate.
            selected=next((j for j,off in enumerate(self.poly_plane_offsets)
                           if off in self.model.plane_edits and
                           self.model.plane_edits[off].polygon==poly.offset),0)
            self.poly_selected_plane.set(labels[selected])
        self.update_poly_plane_panel()

    def _refresh_poly_color_control(self):
        if not self.model or self.selected_poly not in self.model.polygons:
            self.poly_color_index.set('')
            self.poly_color_swatch.configure(bg='#414a5b')
            self.poly_color_explanation.set('Select a polygon to edit its original color index.')
            return
        poly=self.model.polygons[self.selected_poly]
        self.poly_color_index.set(str(poly.color))
        mapped=self.effective_color(poly)
        palette=self.palette
        if palette is not None and 0<=mapped<len(palette):
            self.poly_color_swatch.configure(bg=rgbhex(palette[mapped]))
        else:
            self.poly_color_swatch.configure(bg=rgbhex(self._color(poly)))
        desc=f'Stored color {poly.color}'
        if mapped!=poly.color:
            desc+=f' → RECOLOR preview {mapped} (wrapper remains unchanged)'
        elif self.appearance:
            desc+=' (no RECOLOR remapping for this index)'
        if self.model.face2_pair(poly.offset) is not None:
            desc+=f'. Paired face @{self.model.face2_pair(poly.offset)}.'
        self.poly_color_explanation.set(desc)

    def apply_polygon_color(self):
        if not self.model or self.selected_poly not in self.model.polygons:
            return
        try:
            text=self.poly_color_index.get().strip()
            if not text or any(ch not in '0123456789' for ch in text):
                raise ValueError('Enter a decimal palette index (0–255)')
            color=int(text)
            if color<0 or color>255:
                raise ValueError('Palette index must be between 0 and 255')
            targets=[self.selected_poly]
            paired=self.model.face2_pair(self.selected_poly)
            if paired is not None and self.poly_color_pair.get():
                targets.append(paired)
            edits=[]
            for off in targets:
                before=self.model.polygons[off].color
                if before!=color:
                    self.model.set_polygon_color(off,color)
                    edits.append((off,before,color))
            if edits:
                self.undo_stack.append(('colors',tuple(edits)))
                self.redo_stack.clear()
                self._texture_tile_cache.clear()
                self._texture_tile_cache_bytes=0
                self._texture_photos.clear()
                self.refresh_polygon_list()
                self.refresh_raw()
                self.redraw()
                self.status.set(f'Updated {len(edits)} POLY color(s) to {color}. Save edited 3DO to persist.')
            self._refresh_poly_color_control()
        except (ValueError,KeyError) as exc:
            messagebox.showerror('Invalid polygon color',str(exc))

    def choose_polygon_palette_color(self):
        if not self.model or self.selected_poly not in self.model.polygons:
            return
        if not self.palette or len(self.palette)<256:
            messagebox.showinfo('No palette','Load a 256-color PCX palette first.')
            return
        win=tk.Toplevel(self)
        win.title('Choose 3DO palette color')
        win.configure(bg='#222a38')
        win.resizable(False,False)
        tk.Label(win,text='Select a palette index; Apply saves the selection to the polygon.',
                 bg='#222a38',fg='#dbe5f4').pack(padx=10,pady=(9,5))
        canvas=tk.Canvas(win,width=16*25,height=16*25,bg='#121822',highlightthickness=0)
        canvas.pack(padx=10,pady=4)
        def select(event):
            col=max(0,min(15,event.x//25))
            row=max(0,min(15,event.y//25))
            self.poly_color_index.set(str(row*16+col))
            win.destroy()
        for idx,rgb in enumerate(self.palette[:256]):
            x=(idx%16)*25;y=(idx//16)*25
            canvas.create_rectangle(x+1,y+1,x+24,y+24,
                                    fill=rgbhex(rgb),outline='#26303d')
        canvas.bind('<Button-1>',select)
        tk.Label(win,text='Palette selection fills the index field; click Apply to commit.',
                 bg='#222a38',fg='#9eabc0').pack(pady=(2,9))
        win.transient(self)
        win.grab_set()

    def _split_args(self):
        if not self.model or self.selected_poly not in self.model.polygons:
            raise ValueError('Select a polygon first')
        def get_edge(text):
            if not text:raise ValueError('Select both edges')
            return int(text.split(':',1)[0])-1
        a,b=get_edge(self.split_edge_a.get()),get_edge(self.split_edge_b.get())
        fa,fb=float(self.split_fraction_a.get()),float(self.split_fraction_b.get())
        if a==b or not 0<fa<1 or not 0<fb<1:
            raise ValueError('Use two different edges with fractions between 0 and 1')
        return a,b,fa,fb

    def _existing_vertex_split_args(self):
        if not self.model or self.selected_poly not in self.model.polygons:
            raise ValueError('Select a polygon first')
        def index(value):
            if not value or not value.startswith('#'):
                raise ValueError('Select two vertices')
            return int(value.split()[0][1:])-1
        a=index(self.existing_split_a.get());b=index(self.existing_split_b.get())
        n=len(self.model.polygons[self.selected_poly].refs)
        if n<4 or a==b or (a-b)%n in (1,n-1):
            raise ValueError('Choose two nonadjacent vertices from a polygon with at least four vertices')
        return a,b

    def commit_existing_vertex_split(self):
        if not self.model:return
        try:
            a,b=self._existing_vertex_split_args()
            updated,result=self.model.split_polygon_at_vertices(self.selected_poly,a,b)
        except (FormatError,ValueError,OverflowError) as exc:
            messagebox.showerror('Cannot split polygon',str(exc));return
        message=(f'Split POLY @{result.original_polygon} along vertex #{a+1} → #{b+1}.\n\n'
                 f'Append two polygons @{result.new_polygons[0]} and @{result.new_polygons[1]} '
                 f'under LIST @{result.replacement_list}.\n\n'
                 'New vertices: 0. Existing polygon vertex order, UVs, color, '
                 'texture group, BSP planes, and other model records are preserved. '
                 'The original POLY record remains unreferenced.')
        if not messagebox.askyesno('Commit existing-vertex split?',message):return
        before=self.model
        self.undo_stack.append(('topology',before,updated))
        self.redo_stack.clear()
        old_key=('polygon',result.original_polygon)
        if old_key in self.texture_manual:
            for off in result.new_polygons:
                self.texture_manual[('polygon',off)]=self.texture_manual[old_key]
        self._sync_topology_model(updated,result.new_polygons[0])
        self.existing_split_hint.set('Created POLYs '
               f'@{result.new_polygons[0]} and @{result.new_polygons[1]} with zero new vertices. '
               'Undo restores the original polygon.')
        self.status.set('Existing-vertex polygon split committed. Save edited 3DO to persist.')

    def draw_existing_vertex_split_preview(self):
        if (not self.model or not self.existing_split_preview.get() or self.selected_poly is None
                or self.notebook.select()!=str(self.poly_page)):
            return
        if self.selected_poly not in self.visible_polygon_offsets:return
        try:
            a,b=self._existing_vertex_split_args()
            refs=self.model.polygons[self.selected_poly].refs
            x,y=self._project(self.model.vertices[refs[a]].xyz),self._project(self.model.vertices[refs[b]].xyz)
            self.canvas.create_line(x[0],x[1],y[0],y[1],
                                    fill='#bc83ff',width=3,dash=(6,4),tags='existing_split_preview')
            for sx,sy,_ in (x,y):
                self.canvas.create_oval(sx-5,sy-5,sx+5,sy+5,
                    fill='#bc83ff',outline='#28133c',width=2,tags='existing_split_preview')
        except (ValueError,KeyError,ZeroDivisionError):pass

    def _sync_topology_model(self,model,selected_poly=None):
        self.model=model
        self.poly_order=sorted(model.polygons)
        self.vertex_order=sorted(model.vertices)
        self.dynamic_order=sorted(model.dynamics)
        self.selected=None
        self.selected_poly=(selected_poly if selected_poly in model.polygons else None)
        self.header.set(model.path.name+(' *' if model.dirty else ''))
        self.stats.set(model.summary().replace('\n','  |  '))
        self.listbox.delete(0,'end')
        for ref in self.vertex_order:
            self.listbox.insert('end',self._vertex_list_text(ref))
        self._texture_tile_cache.clear();self._texture_tile_cache_bytes=0
        self._texture_photos.clear()
        self._listed_preview_set=None
        self.refresh_polygon_list()
        self._refresh_polygon_inspector()
        self.update_edit_panel()
        self.refresh_dynamic_list()
        self.refresh_raw()
        self.redraw()

    def commit_polygon_split(self):
        if not self.model:return
        try:
            args=self._split_args()
            updated,result=self.model.split_polygon(self.selected_poly,*args)
        except (FormatError,ValueError,OverflowError) as exc:
            messagebox.showerror('Cannot split polygon',str(exc));return
        message=(f'Original POLY @{result.original_polygon} will be redirected to a new LIST '
                 f'@{result.replacement_list} containing POLYs {result.new_polygons[0]} and '
                 f'{result.new_polygons[1]}.\n\n'
                 f'New vertices: {len(result.new_vertices)}; adjoining polygons updated: '
                 f'{len(result.updated_neighbors)}.\n\n'
                 'The existing FACE/BSP plane is preserved. This is a geometry-only, '
                 'single-polygon split; reshaping the pieces into different planes may '
                 'require manual BSP edits.')
        if result.warnings:
            message+='\n\nReview warnings:\n'+'\n'.join(result.warnings[:4])
        if not messagebox.askyesno('Commit polygon split?',message):return
        before=self.model
        self.undo_stack.append(('topology',before,updated))
        self.redo_stack.clear()
        old_key=('polygon',result.original_polygon)
        if old_key in self.texture_manual:
            for off in result.new_polygons:
                self.texture_manual[('polygon',off)]=self.texture_manual[old_key]
        self._sync_topology_model(updated,result.new_polygons[0])
        self.split_hint.set(f'Split created POLY @{result.new_polygons[0]} and '
                            f'@{result.new_polygons[1]}. Undo restores previous geometry.')
        self.status.set('Polygon split committed to working copy. Save edited 3DO to persist.')

    def draw_polygon_split_preview(self):
        if (not self.model or not self.split_preview.get() or self.selected_poly is None
                or self.notebook.select()!=str(self.poly_page)):return
        if self.selected_poly not in self.visible_polygon_offsets:return
        try:
            a,b,ta,tb=self._split_args()
            poly=self.model.polygons[self.selected_poly]
            refs=poly.refs
            def point(i,t):
                x=self.model.vertices[refs[i]].xyz
                y=self.model.vertices[refs[(i+1)%len(refs)]].xyz
                return tuple(x[j]+(y[j]-x[j])*t for j in range(3))
            x,y=self._project(point(a,ta)),self._project(point(b,tb))
            self.canvas.create_line(x[0],x[1],y[0],y[1],
                                    fill='#40e6e2',width=3,dash=(6,4),tags='split_preview')
            for sx,sy,_ in (x,y):
                self.canvas.create_oval(sx-5,sy-5,sx+5,sy+5,
                    fill='#40e6e2',outline='#103448',width=2,tags='split_preview')
        except (ValueError,KeyError,ZeroDivisionError):pass

    def current_plane_offset(self):
        text=self.poly_selected_plane.get()
        try:
            index=list(self.poly_plane_combo['values']).index(text)
        except ValueError:
            return None
        return self.poly_plane_offsets[index] if index<len(self.poly_plane_offsets) else None

    def update_poly_plane_panel(self):
        po=self.current_plane_offset()
        if po is None or self.model is None or self.selected_poly is None:
            self.poly_plane_info.set('No ancestor FACE/BSP plane. Polygon has no editable plane relationship.')
            self.poly_edit_status.set('')
            return
        plane=self.model.planes[po]
        edit=self.model.plane_edits.get(po)
        effective=None
        try:
            effective=self.model.effective_plane(po)
            desc=', '.join(map(str,effective))
        except FormatError as exc:
            desc=f'ERROR: {exc}'
        diagnostic=''
        if isinstance(effective,tuple) and len(effective)==4:
            distance,percent=self.model.polygon_plane_deviation(self.selected_poly,effective)
            diagnostic=(f'\nMax deviation: {distance:,.1f} raw units '
                        f'({percent*100:.2f}% of bbox diagonal)'
                        + ('  •  noncoplanar is permitted for explicit edits' if distance>1 else ''))
        label=(f'{self.model.plane_relationship(self.selected_poly,po)}\n'
               f'Source: {plane.equation}\nEffective: ({desc}){diagnostic}')
        self.poly_plane_info.set(label)
        self.poly_edit_status.set(f'Override: {edit.mode}' + (' (flipped)' if edit.flip else '')
                                  if edit else 'Override: none (automatic safe-rebuild rules)')
        if edit and edit.mode=='manual' and edit.polygon==self.selected_poly:
            refs=self.model.polygons[self.selected_poly].unique_refs
            for i,ref in enumerate(edit.refs):
                self.poly_ref_selections[i].set(f'{refs.index(ref)+1}: {ref}')

    def _plane_action(self,action,mode=None):
        if self.model is None or self.selected_poly is None:
            return
        off=self.current_plane_offset()
        if off is None:
            messagebox.showinfo('No related plane','This polygon has no ancestor FACE/BSP record to edit.')
            return
        relation=self.model.plane_relationship(self.selected_poly,off)
        if action in ('auto','manual') and relation.startswith('ancestor partition'):
            if not messagebox.askyesno('Non-coplanar BSP partition',
                f'Plane {off} does not lie on this polygon in the source 3DO.\n\n'
                'Using this polygon to replace a sorting/partition plane may change visibility '
                'for many surfaces. Proceed with the override?'):
                return
        before=self.model.plane_edits.get(off)
        try:
            if action=='auto':
                self.model.set_plane_edit(off,self.selected_poly,'auto',flip=(before.flip if before else False))
            elif action=='manual':
                refs=[]
                for field in self.poly_ref_selections:
                    value=field.get()
                    idx=int(value.split(':')[0])-1
                    refs.append(self.poly_ref_options[idx])
                self.model.set_plane_edit(off,self.selected_poly,'manual',tuple(refs),
                                          flip=(before.flip if before else False))
            elif action=='flip':
                self.model.flip_plane(off,self.selected_poly)
            elif action=='clear':
                self.model.restore_plane_edit(off,None)
            else:return
        except (ValueError,IndexError,FormatError) as exc:
            messagebox.showerror('Plane edit rejected',str(exc))
            return
        after=self.model.plane_edits.get(off)
        if before!=after:
            self.undo_stack.append(('plane',off,before,after))
            self.redo_stack.clear()
        self._refresh_polygon_inspector()
        # Retain chosen target when multiple candidate ancestor planes exist.
        self._select_plane_offset(off)
        # Edits should be immediately visible in diagnostic preview.
        self.bsp_mode.set('Rebuilt planes')
        self.redraw()
        self.status.set(f'Plane {off}: {action}  (POLY {self.selected_poly})')

    def _select_plane_offset(self,off):
        if off not in self.poly_plane_offsets:return
        i=self.poly_plane_offsets.index(off)
        self.poly_plane_combo.current(i)
        self.update_poly_plane_panel()

    def auto_polygon_plane(self):self._plane_action('auto')
    def manual_polygon_plane(self):self._plane_action('manual')
    def flip_polygon_plane(self):self._plane_action('flip')
    def clear_polygon_plane(self):self._plane_action('clear')

    @staticmethod
    def _point_in_polygon(x,y,coords):
        inside=False
        j=len(coords)-1
        for i in range(len(coords)):
            xi,yi=coords[i];xj,yj=coords[j]
            if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/(yj-yi)+xi:
                inside=not inside
            j=i
        return inside

    @staticmethod
    def _near_segment(x,y,p,q,limit=7):
        ax,ay=p; bx,by=q
        vx,vy=bx-ax,by-ay
        t=max(0,min(1,((x-ax)*vx+(y-ay)*vy)/(vx*vx+vy*vy or 1)))
        return (x-(ax+t*vx))**2+(y-(ay+t*vy))**2<=limit**2

    def pick_dynamic(self,event):
        for ref,xy in reversed(self._screen_dynamics):
            if len(xy)>2 and self._point_in_polygon(event.x,event.y,xy):
                self.choose_dynamic(ref)
                return
            if len(xy)==2 and self._near_segment(event.x,event.y,*xy):
                self.choose_dynamic(ref)
                return
        self.status.set('No external component hit; select a DYNAMIC record in the Components tab.')

    def pick_polygon(self,event):
        for off,xy in reversed(self._screen_polygons):
            if len(xy)>2 and self._point_in_polygon(event.x,event.y,xy):
                self.choose_polygon(off)
                return
            if len(xy)==2 and self._near_segment(event.x,event.y,*xy):
                self.choose_polygon(off)
                return
        self.status.set('No polygon hit. Right-drag to orbit or choose a polygon in the list.')

    def export_n3_text(self):
        """Write N3 text without losing standalone pointer/annotation mappings."""
        if not self.model:
            messagebox.showinfo('Open a model', 'Open a 3DO or N3 .3D model before exporting.')
            return
        standalone=(self.standalone_n3_binary is not None and self.text_document is not None)
        try:
            if standalone:
                text=export_standalone_text(self.model,self.text_document,self.standalone_n3_binary)
                # Standalone N3 labels (including 'nil') are not binary offsets.
                # The original compiler's Document contains the correct mapping;
                # parse_document(text) defaults to the legacy overlay rules and
                # would reject perfectly valid standalone N3 declarations.
                next_document=self.text_document
            else:
                text=export_text(self.model,self.text_document)
                # Validate metadata *before* touching the destination file.
                next_document=parse_document(text)
        except (FormatError,ValueError,OverflowError,OSError) as exc:
            messagebox.showerror('Cannot export .3D',str(exc))
            return
        source=self.model.path
        out=filedialog.asksaveasfilename(title='Export Papyrus N3 .3D',
                 defaultextension='.3d',initialdir=str(source.parent),
                 initialfile=source.stem+'.3d',
                 filetypes=[('N3 .3D text','*.3d'),('All files','*.*')])
        if not out:return
        target=Path(out)
        if standalone and target.resolve()==source.resolve():
            messagebox.showerror('Choose a separate text file',
                'The original standalone .3D is your annotated source. '
                'Export to a different filename to avoid replacing it.')
            return
        try:
            # Atomic replacement prevents partial files if writing fails.
            # For an unchanged standalone source, preserve CRLF exactly.
            _atomic_write(target,text.encode('utf-8'))
        except (OSError,UnicodeError) as exc:
            messagebox.showerror('Cannot write N3 text',str(exc))
            return
        self.text_document=next_document
        self.status.set(f'Exported {target.name}; N3 pointer labels and comments preserved.')
        if standalone:
            messagebox.showinfo('N3 export saved',
                'Exported the standalone .3D model. Your original source remains unchanged.\n\n'
                'To load the exported text, use File > Open. '
                'Use Save Copy to generate a binary .3DO.')
        else:
            messagebox.showinfo('N3 export saved',
                'Exported the annotated .3D text. Keep it to preserve pointer names '
                'and comments, which cannot be stored in the binary .3DO.')

    def open_standalone_n3(self):
        filename=filedialog.askopenfilename(title='Open standalone Papyrus N3 .3D',
                filetypes=[('Papyrus N3 text','*.3d'),('All files','*.*')])
        if filename:
            self.load_file(filename)

    def import_n3_text(self):
        """Patch binary model or load standalone N3 when no original is open."""
        if not self.model or self.model.path.suffix.lower()=='.3d':
            self.open_standalone_n3()
            return
        if self.model.dirty or self.imported_pending:
            if not messagebox.askyesno('Replace unsaved edits?',
                  'Importing .3D text replaces unsaved changes in the current model. Continue?'):
                return
        filename=filedialog.askopenfilename(title='Import annotated N3 .3D text',
                    initialdir=str(self.model.path.parent),
                    filetypes=[('Papyrus N3 text','*.3d'),('All files','*.*')])
        if not filename:return
        try:
            text=Path(filename).read_text(encoding='utf-8-sig')
            # For an already edited model, import against its current raw state,
            # and never partially modify the displayed model on parse errors.
            original_raw=self.model.raw
            checked,doc=import_text(self.model,text)
        except (OSError,UnicodeError,FormatError,ValueError,OverflowError) as exc:
            messagebox.showerror('N3 import rejected',str(exc))
            return
        self.model=checked
        self.text_document=doc
        self.imported_pending=(checked.raw!=original_raw) or self.imported_pending
        self.selected=None
        self.selected_poly=None
        self.selected_dynamic=None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.poly_order=sorted(checked.polygons)
        self.vertex_order=sorted(checked.vertices)
        self.dynamic_order=sorted(checked.dynamics)
        self.header.set(checked.path.name+(' *' if self.imported_pending else ''))
        self.stats.set(checked.summary().replace('\n','  |  '))
        self.listbox.delete(0,'end')
        for ref in self.vertex_order:
            self.listbox.insert('end',self._vertex_list_text(ref))
        self.refresh_dynamic_list()
        self.refresh_polygon_list()
        self._refresh_polygon_inspector()
        self.update_edit_panel()
        self.refresh_raw()
        self.refresh_geometry_targets()
        self.frame_model()
        self.status.set(f'Imported {Path(filename).name}: validated against original 3DO record topology; '
                        'Save Copy writes the edited binary.')
        messagebox.showinfo('N3 import validated',
            'Imported and validated the text edits in memory.\n'
            'Save Copy to write a new binary .3DO.\n\n'
            'Keep your .3D file for pointer names and comments; they are not stored in .3DO.')

    def open_file(self):
        path=filedialog.askopenfilename(title='Open Papyrus 3DO or N3 .3D',
            filetypes=[('3DO and N3 model files','*.3do *.3d'),
                       ('Papyrus 3DO binary','*.3do'),
                       ('Papyrus N3 text','*.3d'),('All files','*.*')])
        if path: self.load_file(path)

    def load_file(self,path):
        is_n3=Path(path).suffix.lower()=='.3d'
        if not is_n3:
            # Individual car 3DOs contain an appearance wrapper, not local mesh.
            try:
                appearance=read_car_appearance(path)
            except (OSError,AppearanceError):
                appearance=None
            if appearance is not None:
                return self.load_car_appearance(path,appearance=appearance)
        if self.model and (self.model.dirty or self.imported_pending):
            if not messagebox.askyesno('Discard edits?',
                    'Discard unsaved edits and load another model?'):
                return False
        try:
            if is_n3:
                # Read bytes, not read_text(): universal newline conversion would
                # discard the source's original CRLF line endings.
                text=Path(path).read_bytes().decode('utf-8-sig')
                obj,doc=compile_n3_text(text,Path(path))
            else:
                obj=Model(path)
                doc=None
        except (OSError,UnicodeError,FormatError,ValueError,OverflowError) as e:
            messagebox.showerror('Unable to open Papyrus model',str(e))
            return False
        self.model=obj
        self.text_document=doc
        self.standalone_n3_binary=bytes(obj.raw) if is_n3 else None
        self.imported_pending=is_n3
        self.draft_vertices=[]
        self.geometry_drafts.set('No draft vertices (not stored in 3DO until used)')
        self.external_model_cache.clear()
        self.external_resolver.missing.clear()
        self.selected_dynamic=None
        self.dynamic_order=sorted(obj.dynamics)
        self.appearance=None
        self.appearance_info.set('Car appearance: base polygon colors (no RECOLOR file)')
        self.texture_manual.clear()
        self.texture_cache.clear()
        self._mip_path_cache.clear()
        self._texture_photos.clear()
        self._texture_tile_cache.clear()
        self._texture_tile_cache_bytes=0
        self.title(f'ICR2 3DO CAD v1.9 — {Path(path).name}')
        self.selected=None;self.selected_poly=None
        self.undo_stack=[]; self.redo_stack=[]
        self.poly_order=sorted(obj.polygons)
        self.poly_detail.set('Select a polygon to inspect')
        self._refresh_polygon_inspector()
        self.header.set(Path(path).name)
        self.stats.set(obj.summary().replace('\n','  |  '))
        self.vertex_order=sorted(obj.vertices)
        if obj.switches:
            max_threshold=max((threshold for sw in obj.switches.values()
                               for threshold,_ in sw.branches),default=1)
            self.lod_slider.configure(to=max(1,int(max_threshold*1.30)))
            self.lod_mode.set('SWITCH DISTANCE')
            self.lod_distance.set(0)
            self.lod_distance_text.set('0')
        else:
            self.lod_mode.set('All branches')
            self.lod_slider.configure(to=1)
            self.lod_distance.set(0)
            self.lod_distance_text.set('0')
        self.listbox.delete(0,'end')
        for ref in self.vertex_order:
            self.listbox.insert('end',self._vertex_list_text(ref))
        self.refresh_dynamic_list()
        self.frame_model()
        self.update_edit_panel()
        self.refresh_raw()
        self.geometry_anchor.set(str(8484 if 8484 in self.model.polygons else next(iter(self.model.polygons),0)))
        self.refresh_geometry_targets()
        self.refresh_polygon_list()
        warning=' | '.join(obj.warnings)
        if is_n3:
            self.status.set(f'Opened standalone {Path(path).name} (compiled in memory). '
                            'Use Save Copy to write .3DO; keep .3D for comments and labels.')
        else:
            self.status.set(warning or 'Select POLY [T] and assign MIP for texture preview • Right-drag orbit • Scroll zoom')
        return True

    def open_car_appearance(self):
        initial=(self.appearance.path.parent if self.appearance else
                 self.model.path.parent if self.model else Path.cwd())
        path=filedialog.askopenfilename(title='Load individual car RECOLOR 3DO',
             initialdir=str(initial),filetypes=[('Papyrus 3DO','*.3do'),('All files','*.*')])
        if path:self.load_car_appearance(path)

    def load_car_appearance(self,path,*,appearance=None):
        """Apply appearance to matching model; load referenced geometry if needed.

        Never merges the wrapper into the geometry file. Plain geometry Save As
        remains byte-identical unless user edited XYZ/UV/planes separately.
        """
        try:
            app=appearance or read_car_appearance(path)
        except (OSError,AppearanceError) as exc:
            messagebox.showerror('Invalid car appearance 3DO',str(exc))
            return False
        matching=(self.model is not None and self.model.path.stem.casefold()==app.geometry_name.casefold())
        if self.model is not None and not matching:
            choice=messagebox.askyesnocancel('Different base geometry',
                f'{app.path.name} references {app.geometry_name}.3do, but the open model is '
                f'{self.model.path.name}.\n\nYes: open the referenced base geometry\n'
                'No: apply these colors to the existing geometry anyway (preview only)\n'
                'Cancel: make no change')
            if choice is None:return False
            if choice:
                matching=False
            else:
                matching=True  # deliberate preview mismatch, preserve edits
        if not matching:
            base=locate_base_geometry(app,extra_dirs=[Path(__file__).resolve().parent/'fixtures'])
            if base is None:
                selected=filedialog.askopenfilename(
                    title=f'Locate base geometry {app.geometry_name}.3do',
                    initialdir=str(app.path.parent),
                    filetypes=[('Papyrus 3DO','*.3do'),('All files','*.*')])
                if not selected:return False
                base=Path(selected)
                if base.stem.casefold()!=app.geometry_name.casefold():
                    if not messagebox.askyesno('Unexpected geometry',
                        f'Expected {app.geometry_name}.3do, selected {base.name}.\n'
                        'Use this geometry for preview anyway?'):
                        return False
            if not self.load_file(base):return False
        self.appearance=app
        self._texture_tile_cache.clear()
        self._texture_tile_cache_bytes=0
        self._texture_photos=[]
        self._mip_path_cache.clear()
        self._texture_errors=set()
        self.appearance_info.set('Individual car: '+app.description)
        self.title(f'ICR2 3DO CAD v1.9 — {self.model.path.name} + {app.path.name}')
        self.refresh_polygon_list()
        self._refresh_polygon_inspector()
        self.redraw()
        tex=self._find_named_texture(app.texture_name,app.path.parent) if app.texture_name else None
        warning=(' • MIP missing: choose texture folder or place '+app.texture_name+'.mip alongside the wrapper' if not tex else '')
        self.status.set(f'Loaded {app.path.name}: {len(app.mapping)} RECOLOR entries for {self.model.path.name}' + warning)
        return True

    def clear_car_appearance(self):
        if self.appearance is None:return
        self.appearance=None
        self._mip_path_cache.clear()
        self.appearance_info.set('Car appearance: base polygon colors (no RECOLOR file)')
        if self.model:self.title(f'ICR2 3DO CAD v1.9 — {self.model.path.name}')
        self._texture_tile_cache.clear()
        self._texture_tile_cache_bytes=0
        self._texture_photos=[]
        self.refresh_polygon_list()
        self._refresh_polygon_inspector()
        self.redraw()
        self.status.set('Car RECOLOR/MIP preview cleared; geometry and edits unchanged')

    def _vertex_list_text(self,ref):
        v=self.model.vertices[ref]
        star='*' if v.modified or v.uv_modified else ' '
        uvtag=' UV' if v.textured else ''
        return f'{star} {ref:>6}  {v.xyz[0]:>8} {v.xyz[1]:>8} {v.xyz[2]:>8}{uvtag}'

    def update_edit_panel(self):
        if not self.model:
            self.selection_label.set('No model loaded');return
        n=len(self.model.modified_vertices)+len(self.model.modified_uvs)
        self.modified_label.configure(text=f'{n} edits',fg='#ffb862' if n else '#8fa3bb')
        if self.selected is None:
            self.selection_label.set('Click a vertex or select from list')
            for v in self.posvars+self.uvvars:v.set('')
            self.uv_apply.configure(state='disabled')
        else:
            v=self.model.vertices[self.selected]
            self.selection_label.set(f'Vertex at body offset {v.offset}' +
                                     ('  •  UV mapped' if v.textured else '  •  no UV') +
                                     ('  •  modified' if (v.modified or v.uv_modified) else '') +
                                     ('  •  LOD anchor' if v.offset in self.model.lod_anchors else ''))
            for field,value in zip(self.posvars,v.xyz):field.set(str(value))
            for field,value in zip(self.uvvars,(v.uv if v.uv is not None else ('',''))):
                field.set(str(value))
            self.uv_apply.configure(state='normal' if v.textured else 'disabled')
            index=self.vertex_order.index(self.selected)
            self.listbox.delete(index)
            self.listbox.insert(index,self._vertex_list_text(self.selected))
            self.listbox.selection_clear(0,'end')
            self.listbox.selection_set(index)
            self.listbox.see(index)

    def choose(self,ref):
        if not self.model or ref not in self.model.vertices:return
        self.selected=ref
        self.update_edit_panel()
        self.redraw()

    def select_from_list(self,event=None):
        sels=self.listbox.curselection()
        if sels:
            ref=self.vertex_order[sels[0]]
            if ref!=self.selected:
                self.selected=ref;self.update_edit_panel();self.redraw()

    def find_offset(self):
        if not self.model:return
        try:
            text=self.offset_entry.get().strip().lower()
            ref=int(text,16) if text.startswith('0x') else int(text)
            if ref not in self.model.vertices:
                messagebox.showinfo('Vertex not found',f'No vertex at body offset {ref}.')
                return
            self.choose(ref)
        except ValueError:
            messagebox.showwarning('Invalid offset','Enter an integer body offset (decimal or 0x hexadecimal).')

    def apply_uv(self):
        if self.model is None or self.selected is None:return
        v=self.model.vertices[self.selected]
        if not v.textured:return
        try:
            before=v.uv
            values=tuple(int(x.get()) for x in self.uvvars)
            self.model.set_uv(self.selected,values)
            after=v.uv
            if before!=after:
                self.undo_stack.append(('uv',self.selected,before,after))
                self.redo_stack=[]
            self.update_edit_panel();self.redraw()
        except (ValueError,FormatError) as e:
            messagebox.showerror('Invalid UV coordinates',str(e))

    def _slider_distance(self,value):
        self.lod_distance_text.set(str(round(float(value))))
        if hasattr(self,'canvas'):
            self.redraw()

    def _apply_distance_entry(self,event=None):
        try:
            value=int(self.lod_distance_text.get().strip())
            if value<0:raise ValueError()
            self.lod_slider.configure(to=max(value, float(self.lod_slider.cget('to'))))
            self.lod_distance.set(value)
            self.redraw()
        except ValueError:
            self.lod_distance_text.set(str(round(self.lod_distance.get())))

    def commit_vertex(self,new_xyz):
        if self.model is None or self.selected is None:return
        try:
            before=self.model.get_vertex(self.selected).xyz
            self.model.set_vertex(self.selected,new_xyz)
            after=self.model.get_vertex(self.selected).xyz
            if before!=after:
                self.undo_stack.append((self.selected,before,after))
                self.redo_stack=[]
            self.update_edit_panel();self.redraw()
        except (ValueError,FormatError) as e:
            messagebox.showerror('Invalid coordinate',str(e))

    def apply_coordinates(self):
        if not self.model or self.selected is None:return
        try:
            new_xyz=tuple(int(v.get()) for v in self.posvars)
        except ValueError:
            messagebox.showwarning('Invalid coordinates','X, Y, and Z must be whole numbers.')
            return
        self.commit_vertex(new_xyz)

    def _step(self):
        try:
            n=int(self.nudge_step.get())
            if n<=0:raise ValueError()
            return n
        except ValueError:
            messagebox.showwarning('Invalid step','Step must be a positive whole number.')
            return None

    def nudge(self,direction):
        if not self.model or self.selected is None:return
        step=self._step()
        if step is None:return
        coords=list(self.model.vertices[self.selected].xyz)
        coords['XYZ'.index(self.axis.get())] += direction*step
        self.commit_vertex(coords)

    def _after_color_history(self):
        self._texture_tile_cache.clear();self._texture_tile_cache_bytes=0
        self._texture_photos.clear()
        self.refresh_polygon_list();self._refresh_polygon_inspector()
        self.refresh_raw();self.redraw()

    def undo(self):
        if not self.model or not self.undo_stack:return
        record=self.undo_stack.pop()
        if record[0]=='colors':
            _,edits=record
            for off,before,after in edits:self.model.set_polygon_color(off,before)
            self.redo_stack.append(record)
            self._after_color_history()
            return
        if record[0]=='topology':
            _,before,after=record
            self.redo_stack.append(record)
            self._sync_topology_model(before)
            self.refresh_raw()
            return
        if len(record)==4 and record[0]=='plane':
            _,ref,before,after=record
            self.model.restore_plane_edit(ref,before)
            self.redo_stack.append(record)
            self._refresh_polygon_inspector();self.redraw()
            return
        if len(record)==4 and record[0]=='dynamic':
            _,ref,before,after=record
            self.model.set_dynamic(ref,*before)
            self.redo_stack.append(record)
            self.choose_dynamic(ref)
            return
        if len(record)==4:
            _,ref,before,after=record
            self.model.set_uv(ref,before)
        else:
            ref,before,after=record
            self.model.set_vertex(ref,before)
        self.redo_stack.append(record);self.choose(ref)

    def redo(self):
        if not self.model or not self.redo_stack:return
        record=self.redo_stack.pop()
        if record[0]=='colors':
            _,edits=record
            for off,before,after in edits:self.model.set_polygon_color(off,after)
            self.undo_stack.append(record)
            self._after_color_history()
            return
        if record[0]=='topology':
            _,before,after=record
            self.undo_stack.append(record)
            self._sync_topology_model(after)
            self.refresh_raw()
            return
        if len(record)==4 and record[0]=='plane':
            _,ref,before,after=record
            self.model.restore_plane_edit(ref,after)
            self.undo_stack.append(record)
            self._refresh_polygon_inspector();self.redraw()
            return
        if len(record)==4 and record[0]=='dynamic':
            _,ref,before,after=record
            self.model.set_dynamic(ref,*after)
            self.undo_stack.append(record)
            self.choose_dynamic(ref)
            return
        if len(record)==4:
            _,ref,before,after=record
            self.model.set_uv(ref,after)
        else:
            ref,before,after=record
            self.model.set_vertex(ref,after)
        self.undo_stack.append(record);self.choose(ref)

    def reset_edits(self):
        if self.model and self.model.dirty:
            if not messagebox.askyesno('Reset edits?', 'Reset XYZ, UV, explicit FACE/BSP and DYNAMIC placement edits?'):
                return
            if self.model.topology_history:
                source_path=self.model.path
                self.model=(Model(source_path,raw_data=self.standalone_n3_binary)
                            if source_path.suffix.lower()=='.3d' and self.standalone_n3_binary is not None
                            else Model(source_path))
                self.poly_order=sorted(self.model.polygons)
                self.vertex_order=sorted(self.model.vertices)
                self.selected=None;self.selected_poly=None
                self.texture_manual={k:v for k,v in self.texture_manual.items()
                                      if k[0]!='polygon' or k[1] in self.model.polygons}
                self.refresh_polygon_list()
            self.model.reset();self.undo_stack=[];self.redo_stack=[]
            self.listbox.delete(0,'end')
            for ref in self.vertex_order:self.listbox.insert('end',self._vertex_list_text(ref))
            self.update_edit_panel()
            self._refresh_polygon_inspector()
            self.redraw()

    def _basis(self):
        # Display transform reflects Y, so +Y now points in the opposite
        # screen direction from v0.4. Raw 3DO coordinates, drag edits and
        # saved data are NOT reflected or rewritten.
        az,el=self.azimuth,self.elevation
        right=(math.cos(az),math.sin(az),0)
        up=(-math.sin(az)*math.sin(el),math.cos(az)*math.sin(el),math.cos(el))
        toward=(math.sin(az)*math.cos(el),-math.cos(az)*math.cos(el),math.sin(el))
        return right,up,toward

    def _camera_distance(self):
        # In perspective view, mouse-wheel zoom is a camera dolly, not a
        # change to the model's stored position or SWITCH DISTANCE threshold.
        return max(1.0, 1.65*(self.extent or 1.0)/max(self.zoom,0.0001))

    def _camera_position(self):
        toward=self._basis()[2]
        distance=(self._camera_distance() if self.projection.get()=='Perspective (depth)'
                  else max(1.0,self.extent*4))
        return tuple(self.center[i]+toward[i]*distance for i in range(3))

    def _near_plane(self):
        return max(1.,self._camera_distance()*0.002)

    def _view_coordinates(self,point):
        right,up,toward=self._basis()
        delta=sub(point,self.center)
        return (dot(delta,right),dot(delta,up),
                self._camera_distance()-dot(delta,toward),dot(delta,toward))

    def _screen_from_view(self,x,y,z,depth):
        w=self.canvas.winfo_width();h=self.canvas.winfo_height()
        if self.projection.get()=='Perspective (depth)':
            # Focal length from a physical field-of-view. Objects farther
            # from the camera shrink; there is no perspective in ortho mode.
            if z<self._near_plane():
                return (-1000000.,-1000000.,depth)
            focal=min(w,h)/(2*math.tan(math.radians(self.fov_degrees)/2))
            factor=focal/z
        else:
            factor=self.scale
        return (w/2+self.pan[0]+x*factor,
                h/2+self.pan[1]-y*factor,depth)

    def _project(self,point):
        return self._screen_from_view(*self._view_coordinates(point))

    def _project_polygon(self, points):
        """Project polygon/line and clip it against the perspective near plane."""
        if self.projection.get()!='Perspective (depth)':
            return [self._project(p) for p in points]
        verts=[self._view_coordinates(p) for p in points]
        near=self._near_plane()
        if not verts:
            return []
        if len(verts)==1:
            return [self._screen_from_view(*verts[0])] if verts[0][2]>=near else []
        if len(verts)==2:
            a,b=verts
            if a[2]<near and b[2]<near:return []
            if (a[2]<near)!=(b[2]<near):
                t=(near-a[2])/(b[2]-a[2])
                cut=tuple(a[i]+t*(b[i]-a[i]) for i in range(4))
                if a[2]<near:a=cut
                else:b=cut
            verts=[a,b]
        else:
            # Sutherland-Hodgman clipping preserves original vertex order.
            clipped=[]
            previous=verts[-1]
            for cur in verts:
                pi=previous[2]>=near
                ci=cur[2]>=near
                if pi!=ci:
                    t=(near-previous[2])/(cur[2]-previous[2])
                    clipped.append(tuple(previous[i]+t*(cur[i]-previous[i]) for i in range(4)))
                if ci:clipped.append(cur)
                previous=cur
            verts=clipped
        return [self._screen_from_view(*v) for v in verts]

    def set_camera_view(self, view):
        """Change viewing direction without changing model geometry."""
        presets={'Three-quarter':(35,25),'Top':(0,89),'Front':(0,0),'Side':(90,0)}
        if view not in presets:
            raise ValueError(f'Unknown camera view: {view}')
        azimuth,elevation=presets[view]
        self.azimuth=math.radians(azimuth)
        self.elevation=math.radians(elevation)
        self.redraw()
        self.status.set(f'{view} camera view • Right-drag to orbit')

    def frame_selection(self):
        """Center and zoom the current selection without changing model data."""
        if not self.model:return
        page=self.notebook.select()
        points=[]
        if page in (str(self.poly_page),str(self.geometry_page)) and self.selected_poly in self.model.polygons:
            poly=self.model.polygons[self.selected_poly]
            points=[self.model.vertices[ref].xyz for ref in poly.unique_refs]
        elif page==str(self.vertex_page) and self.selected in self.model.vertices:
            points=[self.model.vertices[self.selected].xyz]
        elif page==str(self.component_page) and self.selected_dynamic in self.model.dynamics:
            placement=self.model.dynamics[self.selected_dynamic]
            points=[placement.xyz]
            try:
                faces,_=gather_faces(self.model,None,(0.,0.,1e9),'off',
                                     self.external_resolver,cache=self.external_model_cache)
                for face in faces:
                    if face.placement!=self.selected_dynamic:
                        continue
                    if isinstance(face,RenderSprite):
                        sprite=face.source.pmp_sprites[face.offset]
                        points.append(face.transform.apply(face.source.vertices[sprite.vertex_ref].xyz))
                    else:
                        polygon=face.source.polygons[face.offset]
                        points.extend(face.transform.apply(face.source.vertices[ref].xyz)
                                      for ref in polygon.unique_refs)
            except (FormatError,ValueError,OverflowError,OSError):
                pass
        if not points:
            self.status.set('Select a visible vertex, polygon or part before framing it.')
            return
        lo=[min(p[i] for p in points) for i in range(3)]
        hi=[max(p[i] for p in points) for i in range(3)]
        self.center=tuple((a+b)/2 for a,b in zip(lo,hi))
        span=max(hi[i]-lo[i] for i in range(3))
        self.extent=max(1.0,span*1.5,self._model_extent*0.08)
        self.zoom=1.0
        self.pan=(0.0,0.0)
        self.redraw()
        self.status.set('Framed current selection • F frames the entire model.')

    def frame_model(self):
        if not self.model:
            self.center=(0,0,0); self.extent=1;self.redraw();return
        points=[v.xyz for v in self.model.vertices.values()]
        if self.model.dynamics:
            try:
                faces,_=gather_faces(self.model,None,(0.,0.,1e9),'off',
                    self.external_resolver,cache=self.external_model_cache)
                for face in faces:
                    if face.placement is None:continue
                    if isinstance(face,RenderSprite):
                        sprite=face.source.pmp_sprites[face.offset]
                        points.append(face.transform.apply(face.source.vertices[sprite.vertex_ref].xyz))
                        continue
                    poly=face.source.polygons[face.offset]
                    points.extend(face.transform.apply(face.source.vertices[ref].xyz)
                                  for ref in poly.unique_refs)
            except (FormatError,ValueError,OverflowError):
                pass
        if not points:
            self.center=(0,0,0);self.extent=1;self.redraw();return
        lo=[min(p[i] for p in points) for i in range(3)]
        hi=[max(p[i] for p in points) for i in range(3)]
        self.center=tuple((a+b)/2 for a,b in zip(lo,hi))
        self.extent=max(hi[i]-lo[i] for i in range(3)) or 1
        self._model_extent=self.extent
        self.zoom=1;self.pan=(0.0,0.0)
        self.redraw()

    def effective_color(self,poly,source_model=None):
        if source_model is not None and source_model is not self.model:
            return poly.color
        return self.appearance.map_color(poly.color) if self.appearance else poly.color

    def _color_label(self,poly):
        changed=self.effective_color(poly)
        return str(poly.color) if changed==poly.color else f'{poly.color} → {changed}'

    def _color(self,poly,source_model=None):
        color=self.effective_color(poly,source_model)
        if self.palette and 0<=color<256:
            return self.palette[color]
        # Neutral CAD preview hues; these are NOT ICR2 palette colors.
        h=((color*37)%360)/360.0
        sat=0.20 if poly.kind==1 else 0.37
        r,g,b=colorsys.hsv_to_rgb(h,sat,0.72)
        return tuple(int(255*x) for x in (r,g,b))

    def _polygon_shade(self,poly,source_model=None,transform=None):
        if not self.lighting.get():return 1.0
        source=source_model or self.model
        transform=transform or Transform()
        points=[transform.apply(source.vertices[r].xyz) for r in poly.unique_refs]
        if len(points)<3:return 0.73
        normal=None
        for j in range(1,len(points)-1):
            c=cross(sub(points[j],points[0]),sub(points[j+1],points[0]))
            length=math.sqrt(dot(c,c))
            if length>0:normal=[a/length for a in c];break
        toward=self._basis()[2]
        return 0.73 if normal is None else (0.42+0.50*abs(dot(normal,toward)))

    def _polygon_fill(self,poly,source_model=None,transform=None):
        base=self._color(poly,source_model)
        shade=self._polygon_shade(poly,source_model,transform)
        if shade==1.0:return rgbhex(base)
        return rgbhex(tuple(max(22,int(v*shade)) for v in base))

    def _texture_sampling_scale(self):
        static={'Fast (50%)':0.50,'Balanced (75%)':0.75,'Full (100%)':1.0}
        quality=static.get(self.texture_quality.get(),0.75)
        # Preserve high precision for idle inspection; coarser sampling
        # reduces CPU cost by roughly the square of the scale during motion.
        if self._interactive_view:
            return min(quality,0.40 if quality<1.0 else 0.55)
        return quality

    def request_view_redraw(self):
        # Coalesce motion events; schedule a high-quality idle pass.
        self._interactive_view=True
        if self._pending_view_redraw is None:
            self._pending_view_redraw=self.after(16,self._flush_view_redraw)
        if self._pending_refine is not None:
            self.after_cancel(self._pending_refine)
        self._pending_refine=self.after(180,self._refine_view)

    def _flush_view_redraw(self):
        self._pending_view_redraw=None
        if self.winfo_exists():self.redraw()

    def _refine_view(self):
        self._pending_refine=None
        self._interactive_view=False
        if self._pending_view_redraw is not None:
            self.after_cancel(self._pending_view_redraw)
            self._pending_view_redraw=None
        if self.winfo_exists():self.redraw()

    def finish_view_motion(self,event=None):
        # Restore stationary preview quality after releasing a drag.
        if self._pending_refine is not None:
            self.after_cancel(self._pending_refine)
            self._pending_refine=None
        if self._pending_view_redraw is not None:
            self.after_cancel(self._pending_view_redraw)
            self._pending_view_redraw=None
        if self._interactive_view:
            self._interactive_view=False
            self.redraw()

    def redraw(self):
        if not hasattr(self,'canvas'):return
        _redraw_start=perf_counter()
        c=self.canvas
        self._update_selection_summary()
        c.delete('all')
        w=max(c.winfo_width(),20);h=max(c.winfo_height(),20)
        self.scale=min(w,h)*0.76/(self.extent or 1)*self.zoom
        if not self.model:
            self._screen_polygons=[]
            c.create_text(w/2,h/2,text='Open a .3DO file to begin',fill='#a0aec0',
                          font=('Segoe UI',18))
            return
        if not self.model.vertices:
            c.create_text(w/2,h/2,text='No local geometry in this 3DO.\nIt may reference external models.',
                          fill='#b3c3d8',font=('Segoe UI',14),justify='center')
            return
        if self.show_axes.get():
            self.draw_axes()
        use_switch=self.lod_mode.get()=='SWITCH DISTANCE'
        switch_distance=self.lod_distance.get() if use_switch else None
        plane_choice=self.bsp_mode.get()
        bsp_mode={'Off (show all)':'off', 'Original 3DO planes':'original',
                  'Rebuilt planes':'rebuilt'}[plane_choice]
        # Orthographic projection uses a representative distant camera;
        # perspective uses the camera's actual 3D position for BSP tests.
        camera=self._camera_position()
        preview_error=None
        try:
            offsets,preview,lods=self.model.switched_polygons(switch_distance,camera,bsp_mode)
        except (FormatError,ValueError,OverflowError) as exc:
            # During a vertex drag, an explicit manual plane may temporarily
            # become nonplanar. Keep the CAD view usable but block saving.
            preview_error=str(exc)
            offsets,preview,lods=self.model.switched_polygons(switch_distance,camera,'original')
        self.visible_polygon_offsets=set(offsets)
        active_polys=[self.model.polygons[i] for i in offsets]
        self.active_vertices={r for poly in active_polys for r in poly.unique_refs}
        info=f'{preview["visible"]}/{len(self.model.polygons)} polygons  •  BSP planes checked: {preview["tested_planes"]}'
        if preview_error:
            info+='  •  INVALID EDIT (original BSP preview): '+preview_error[:95]
        if lods:
            info+='  •  LOD: '+', '.join(f'@{off} ≥{threshold:,} → {ptr}' for off,threshold,ptr in lods[:3])
        elif use_switch and not self.model.switches:
            info+='  •  No SWITCH DISTANCE node'
        self.preview_stats.set(info)
        if hasattr(self,'poly_tree') and self.poly_only_visible.get():
            old=getattr(self,'_listed_preview_set',None)
            if old!=self.visible_polygon_offsets:
                self._listed_preview_set=set(self.visible_polygon_offsets)
                self.refresh_polygon_list()
        if self.selected_poly is not None:
            selected_flag=('VISIBLE' if self.selected_poly in self.visible_polygon_offsets
                           else ('HIDDEN (ghost outline)' if self.show_hidden_polygon_outline.get() else 'HIDDEN'))
            poly=self.model.polygons[self.selected_poly]
            self.poly_detail.set(f'POLY @{poly.offset}  •  {len(poly.unique_refs)} unique vertices  •  '
                                 f'Color {self._color_label(poly)}  •  Group {poly.group}  •  {selected_flag}')
        items=[]
        self._screen_dynamics=[]
        # Render each nested model precisely where its DYNAMIC record occurs
        # within the original LIST / BSP traversal. External sources are
        # immutable; selected components only edit placement transforms.
        if self.model.dynamics:
            faces,failures=gather_faces(self.model,switch_distance,camera,bsp_mode,
                              self.external_resolver,cache=self.external_model_cache)
            self._dynamic_failures=failures
            for face in faces:
                if isinstance(face,RenderSprite):
                    items.append(('pmp',face))
                    continue
                source=face.source
                poly=source.polygons[face.offset]
                pts=self._project_polygon([
                    face.transform.apply(source.vertices[v].xyz) for v in poly.unique_refs])
                if len(pts)<2:continue
                items.append((poly,pts,source,face.transform,face.placement,face.texture_override))
        else:
            self._dynamic_failures={}
            identity=Transform()
            for poly in active_polys:
                refs=poly.unique_refs
                if len(refs)<2:continue
                pts=self._project_polygon([self.model.vertices[v].xyz for v in refs])
                if len(pts)<2:continue
                items.append((poly,pts,self.model,identity,None,None))
        self._screen_polygons=[]
        self._texture_photos=[]  # Keep Tk PhotoImage objects alive per redraw
        texture_count=0
        texture_unassigned=0
        # No global depth sort in EITHER mode. In particular, LIST children
        # are authored back-to-front, so a depth sort here would corrupt
        # intentional overlap even in the no-BSP preview. BSP traversal
        # may reorder BSP branches, but must not reorder LIST siblings.
        pmp_count=0
        for entry in items:
            if len(entry)==2 and entry[0]=='pmp':
                if self.show_faces.get() and self.show_textures.get():
                    self.draw_pmp_sprite(entry[1])
                    pmp_count+=1
                continue
            p,pts,source,transform,placement,texture_override=entry
            if placement is None:
                self._screen_polygons.append((p.offset,[(t[0],t[1]) for t in pts]))
            else:
                self._screen_dynamics.append((placement,[(t[0],t[1]) for t in pts]))
            xy=[a for point in pts for a in point[:2]]
            if len(pts)>=3 and self.show_faces.get():
                image_made=False
                if p.kind==2 and self.show_textures.get():
                    tex=self.get_polygon_texture(p,source,texture_override)
                    if tex is not None and self.palette and TEXTURE_AVAILABLE:
                        mapped=self._project_textured_polygon(p,source,transform)
                        if len(mapped)>=3:
                            brightness=self._polygon_shade(p,source,transform)
                            sample_scale=self._texture_sampling_scale()
                            # Projected XYZ/UV is part of the key, so edits
                            # cannot reuse old pixels. Palette and texture
                            # identity account for reloads and reassignment.
                            key=(str(source.path),p.offset,id(tex),id(self.palette),tuple(mapped),
                                 self.projection.get(),self.texture_repeat.get(),
                                 brightness,sample_scale,w,h)
                            cached=self._texture_tile_cache.get(key)
                            if cached is not None:
                                self._texture_tile_cache.move_to_end(key)
                                photo,ox,oy,allocated=cached
                                self._texture_photos.append(photo)
                                c.create_image(ox,oy,image=photo,anchor='nw',tags='poly')
                                image_made=True; texture_count+=1
                            else:
                                tile=rasterize_polygon(tex,self.palette,mapped,(w,h),
                                    perspective=self.projection.get()=='Perspective (depth)',
                                    repeat=self.texture_repeat.get(),
                                    brightness=brightness,sample_scale=sample_scale)
                                if tile is not None:
                                    image,ox,oy=tile
                                    try:
                                        photo=ImageTk.PhotoImage(image,master=self)
                                        self._texture_photos.append(photo)
                                        c.create_image(ox,oy,image=photo,anchor='nw',tags='poly')
                                        image_made=True; texture_count+=1
                                        if not self._interactive_view:
                                            allocated=image.width*image.height*4
                                            self._texture_tile_cache[key]=(photo,ox,oy,allocated)
                                            self._texture_tile_cache_bytes+=allocated
                                            # 16 MiB / 96 entries bounds cache
                                            # memory even on large car models.
                                            while (self._texture_tile_cache_bytes>16*1024*1024 or
                                                   len(self._texture_tile_cache)>96):
                                                _,old=self._texture_tile_cache.popitem(last=False)
                                                self._texture_tile_cache_bytes-=old[3]
                                    except (tk.TclError,ValueError):
                                        pass
                    elif tex is None:
                        texture_unassigned+=1
                if not image_made:
                    c.create_polygon(*xy,fill=self._polygon_fill(p,source,transform),outline='',tags='poly')
            if self.show_edges.get():
                if len(pts)>=3:
                    c.create_line(*xy,pts[0][0],pts[0][1],fill='#596a82',width=0.8,tags='edge')
                else:
                    c.create_line(*xy,fill='#71829b',tags='edge')
        if self.model.dynamics:
            shown={ref for ref,_ in self._screen_dynamics}
            info+=f'  •  {len(shown)}/{len(self.model.dynamics)} external placements'
            if self._dynamic_failures:
                info+=f'  •  {len(self._dynamic_failures)} unresolved'
            self.preview_stats.set(info)
        if pmp_count:
            info+=f'  •  {pmp_count} PMP sprites'
        if self.show_textures.get() and texture_count:
            self.preview_stats.set(info+f'  •  {texture_count} textured')
        elif self.show_textures.get() and texture_unassigned:
            self.preview_stats.set(info+f'  •  {texture_unassigned} textured polys need MIPs')
        if (self.notebook.select()==str(self.component_page) and
                self.selected_dynamic is not None):
            for ref,coords in self._screen_dynamics:
                if ref!=self.selected_dynamic or len(coords)<2:continue
                xy=[val for point in coords for val in point]
                if len(coords)>=3:
                    c.create_line(*xy,coords[0][0],coords[0][1],
                                   fill='#ffdf68',width=2.1,tags='selected_dynamic')
                else:
                    c.create_line(*xy,fill='#ffdf68',width=2.1,tags='selected_dynamic')
        selected_displayable=(self.selected_poly is not None and
                              self.selected_poly in self.model.polygons and
                              (self.selected_poly in self.visible_polygon_offsets or
                               self.show_hidden_polygon_outline.get()))
        if selected_displayable:
            sel=self.model.polygons[self.selected_poly]
            projected=self._project_polygon([self.model.vertices[r].xyz for r in sel.unique_refs])
            pts=[n for triple in projected for n in triple[:2]]
            if len(projected)>=3:
                self.canvas.create_polygon(*pts,fill='',outline='#ffdf68',width=3,
                                           dash=() if sel.offset in self.visible_polygon_offsets else (5,5),
                                           tags='selected_poly')
            elif len(projected)==2:
                self.canvas.create_line(*pts,fill='#ffdf68',width=4,tags='selected_poly')
            # The inspector already names this polygon. Suppress its
            # centroid label while drawing per-vertex numbers, so it does
            # not obscure the numbered markers on narrow polygons.
            numbering=(self.notebook.select()==str(self.poly_page)
                       and self.poly_vertex_labels.get())
            if projected and not numbering:
                mx=sum(v[0] for v in projected)/len(projected)
                my=sum(v[1] for v in projected)/len(projected)
                self.canvas.create_text(mx,my-14,text=f'POLY {sel.offset}',
                                        fill='#ffdf68',font=('Consolas',10,'bold'))
        # Overlay ordered polygon vertex labels after fills/edges, so each
        # label remains readable even if selected vertices share other faces.
        # These are 1-based *polygon list* indices, not 3DO body offsets.
        if (self.notebook.select()==str(self.poly_page) and
                self.poly_vertex_labels.get() and selected_displayable):
            sel=self.model.polygons[self.selected_poly]
            self.draw_selected_polygon_numbers(sel)
        self.draw_polygon_split_preview()
        self.draw_existing_vertex_split_preview()
        if (self.notebook.select()==str(self.poly_page) and
                self.selected_poly is not None):
            self.draw_selected_plane_direction(camera, bsp_mode)
        if self.notebook.select()==str(self.geometry_page):
            for j, v in enumerate(self.draft_vertices,1):
                sx,sy,_=self._project(v[:3])
                c.create_oval(sx-5,sy-5,sx+5,sy+5,fill='#47dfbd',outline='#004e40',width=2)
                c.create_text(sx+9,sy-10,text=f'V{j}',fill='#83ffe1',anchor='sw',
                              font=('Consolas',10,'bold'))
        if self.show_points.get():
            for ref in self.active_vertices:
                if ref==self.selected:continue
                v=self.model.vertices[ref]
                x,y,_=self._project(v.xyz)
                if not -10<x<w+10 or not -10<y<h+10:continue
                rad=2.3 if len(self.model.vertices)<2500 else 1.7
                color='#ffae62' if v.modified else '#b8cced'
                c.create_oval(x-rad,y-rad,x+rad,y+rad,fill=color,outline='',tags='dot')
        if self.selected is not None and self.selected in self.model.vertices:
            x,y,_=self._project(self.model.vertices[self.selected].xyz)
            c.create_oval(x-8,y-8,x+8,y+8,outline='#fff0a0',width=2)
            c.create_line(x-13,y,x+13,y,fill='#fff0a0',width=1)
            c.create_line(x,y-13,x,y+13,fill='#fff0a0',width=1)
            c.create_text(x+12,y-16,text=str(self.selected),fill='#fff0a0',anchor='sw',
                          font=('Consolas',10,'bold'))
        c.create_text(16,12,text=f'{self.projection.get().upper()}  •  Z UP  •  +Y REVERSED IN VIEW  •  RAW 3DO COORDINATES',
                      fill='#95a9c4',font=('Consolas',9),anchor='nw')
        c.create_text(16,h-16,text=f'AZ {math.degrees(self.azimuth):.0f}°   EL {math.degrees(self.elevation):.0f}°   ZOOM {self.zoom:.2f}×  •  {"LIT" if self.lighting.get() else "UNLIT"}  •  {self.palette_source}',
                      fill='#8194aa',font=('Consolas',9),anchor='sw')
        self.last_render_seconds=perf_counter()-_redraw_start
        if self.show_textures.get() and texture_count:
            self.preview_stats.set(self.preview_stats.get()+
                f'  •  draw {self.last_render_seconds*1000:.0f} ms'
                f' ({int(self._texture_sampling_scale()*100)}% texture)')

    def draw_pmp_sprite(self, placement):
        """Draw one viewpoint-selected PMP/PMP2 as a screen-facing bitmap.

        The sprite's 3DO size is interpreted as the width/height of the
        nontransparent picture. This is a viewport approximation; Papyrus's
        exact sprite scaling and horizon conventions remain unverified.
        """
        if (not self.show_faces.get() or not self.show_textures.get() or
                not TEXTURE_AVAILABLE or not self.palette):
            return
        source=placement.source
        sprite=source.pmp_sprites[placement.offset]
        location=self.external_resolver.find(sprite.name,source.path,
                       extension='.pmp')
        if location is None:
            self._dynamic_failures[(source.path,placement.offset)]=f'{sprite.name}.pmp not found'
            return
        key=(location.resolve(),id(self.palette))
        try:
            if key not in self._pmp_cache:
                self._pmp_cache[key]=load_pmp(location,self.palette)
            img=self._pmp_cache[key]
        except (OSError,PMPError,ValueError) as exc:
            self._dynamic_failures[(source.path,placement.offset)]=f'{sprite.name}.pmp: {exc}'
            return
        point=placement.transform.apply(source.vertices[sprite.vertex_ref].xyz)
        center=self._project(point)
        if abs(center[0])>100000 or abs(center[1])>100000:
            return
        right=self._basis()[0]
        endpoint=tuple(point[i]+right[i]*abs(sprite.size) for i in range(3))
        ext=self._project(endpoint)
        scale=abs(ext[0]-center[0]) / max(1,img.rgba.width,img.rgba.height)
        # A minimum size prevents disappearing in distant LODs, while a
        # maximum bounds pathological zoom and raster allocations.
        if scale<=0:
            return
        dstw=max(1,min(2048,int(round(img.rgba.width*scale))))
        dsth=max(1,min(2048,int(round(img.rgba.height*scale))))
        if dstw<2 or dsth<2:
            return
        sx=dstw/img.rgba.width
        sy=dsth/img.rgba.height
        x=center[0]+(img.bounds[0]-128)*sx
        y=center[1]+(img.bounds[1]-128)*sy
        rendered=img.rgba.resize((dstw,dsth),Image.Resampling.NEAREST)
        try:
            photo=ImageTk.PhotoImage(rendered,master=self)
            self._texture_photos.append(photo)
            self.canvas.create_image(x,y,image=photo,anchor='nw',tags='pmp')
            if placement.placement is not None:
                self._screen_dynamics.append((placement.placement,[(x,y),(x+dstw,y),
                    (x+dstw,y+dsth),(x,y+dsth)]))
        except (tk.TclError,ValueError):
            return

    def draw_selected_plane_direction(self, camera, bsp_mode):
        """Diagnostic of the *currently previewed* FACE/BSP plane.

        Anchors the normal at the selected polygon's centroid for visibility.
        This is an orientation indicator, not the actual plane location.
        """
        po=self.current_plane_offset()
        if po is None or po not in self.model.planes:
            return
        stored=self.model.planes[po]
        try:
            eq=(stored.equation if bsp_mode=='original'
                else self.model.effective_plane(po))
        except (FormatError, ValueError, OverflowError):
            return
        n=eq[:3]
        magnitude=math.sqrt(dot(n,n))
        if magnitude==0:
            return
        normal=tuple(float(k)/magnitude for k in n)
        poly=self.model.polygons[self.selected_poly]
        verts=[self.model.vertices[r].xyz for r in poly.unique_refs]
        if not verts:
            return
        center=tuple(sum(v[i] for v in verts)/len(verts) for i in range(3))
        tip=tuple(center[i]+normal[i]*self.extent*0.20 for i in range(3))
        x1,y1,_=self._project(center)
        x2,y2,_=self._project(tip)
        side=dot(n,camera)+eq[3]
        front='front (+)' if side>=0 else 'back (-)'
        source=('BSP OFF (reference only)' if bsp_mode=='off' else
                'stored' if bsp_mode=='original' else
                ('edited' if po in self.model.plane_edits else 'effective'))
        label=f'{NAMES[stored.kind]} @{po}  •  {source} plane  •  camera: {front}'
        # The side and normal labels provide a visible confirmation even for
        # pure draw-order nodes that do not change the number of polygons.
        self.canvas.create_text(16,30,text=label,fill='#ffdd87',anchor='nw',
                                font=('Consolas',10,'bold'),tags='plane_normal')
        distance=math.hypot(x2-x1,y2-y1)
        if distance>=12:
            self.canvas.create_line(x1,y1,x2,y2,fill='#ff8deb',width=3,
                                    arrow='last',arrowshape=(12,14,5),tags='plane_normal')
            self.canvas.create_text(x2+7,y2-7,text='N+',anchor='sw',
                                    fill='#ffd0f4',font=('Consolas',11,'bold'),
                                    tags='plane_normal')
        else:
            # Normal is nearly end-on: indicate its direction along view.
            viewer=dot(n,self._basis()[2])
            mark='⊙ N+ toward viewer' if viewer>0 else '⊗ N+ away from viewer'
            self.canvas.create_oval(x1-5,y1-5,x1+5,y1+5,outline='#ff8deb',width=2,
                                    tags='plane_normal')
            self.canvas.create_text(x1+12,y1-11,text=mark,anchor='sw',
                                    fill='#ffd0f4',font=('Consolas',10,'bold'),
                                    tags='plane_normal')

    @staticmethod
    def polygon_vertex_label_groups(poly):
        """Group positions by vertex record to handle repeated closing refs.

        Return ordered (ref, '#1' or '#1/#5') labels matching list indices.
        """
        by_ref={}
        for i,ref in enumerate(poly.refs,1):
            by_ref.setdefault(ref,[]).append(i)
        return [(ref, '/'.join(f'#{number}' for number in numbers))
                for ref,numbers in by_ref.items()]

    def draw_selected_polygon_numbers(self,poly):
        # Keep labels adjacent to their vertices rather than placing them at
        # the vertices themselves, which would obscure handles and outlines.
        # Basic proximity staggering prevents labels disappearing when
        # multiple *different* vertex records share a screen position.
        taken=[]
        for ref,label in self.polygon_vertex_label_groups(poly):
            if ref not in self.model.vertices:
                continue
            x,y,_=self._project(self.model.vertices[ref].xyz)
            used=0
            tx,ty=x+11,y-12
            while any(abs(tx-px)<25 and abs(ty-py)<15 for px,py in taken) and used<12:
                used+=1
                tx=x+11+(used//4)*38
                ty=y-12+(used%4)*19
            taken.append((tx,ty))
            self.canvas.create_oval(x-5,y-5,x+5,y+5,fill='#ffdc68',
                                    outline='#1b2030',width=1.1,tags='poly_number')
            self.canvas.create_line(x+4,y-4,tx,ty,fill='#ffdc68',
                                    width=1,tags='poly_number')
            # Two text passes create a dark halo usable over shaded faces.
            self.canvas.create_text(tx+1,ty+1,text=label,anchor='sw',
                                    fill='#09101c',font=('Consolas',11,'bold'),
                                    tags='poly_number')
            self.canvas.create_text(tx,ty,text=label,anchor='sw',
                                    fill='#fff0ac',font=('Consolas',11,'bold'),
                                    tags='poly_number')

    def draw_axes(self):
        origin=self._project(self.center)
        radius=self.extent*0.28
        for axis,v,color in [('X',(radius,0,0),'#f08377'),('Y',(0,radius,0),'#7cdaa3'),('Z',(0,0,radius),'#7caafb')]:
            p=(self.center[0]+v[0],self.center[1]+v[1],self.center[2]+v[2])
            dest=self._project(p)
            self.canvas.create_line(origin[0],origin[1],dest[0],dest[1],fill=color,
                                    width=2,arrow='last')
            self.canvas.create_text(dest[0]+7,dest[1],text=axis,fill=color,anchor='w',
                                    font=('Consolas',10,'bold'))

    def start_pick(self,event):
        if not self.model:return
        if self.notebook.select() in (str(self.poly_page),str(self.geometry_page)):
            self.pick_polygon(event)
            if self.notebook.select()==str(self.geometry_page) and self.selected_poly is not None:
                self.geometry_anchor.set(str(self.selected_poly))
                self.refresh_geometry_targets()
            self._drag=None
            return
        if self.notebook.select()==str(self.component_page):
            self.pick_dynamic(event)
            self._drag=None
            return
        closest=None
        best=11**2
        near_depth=-math.inf
        for ref in self.active_vertices:
            v=self.model.vertices[ref]
            sx,sy,depth=self._project(v.xyz)
            d2=(sx-event.x)**2+(sy-event.y)**2
            if d2<best-0.5 or (abs(d2-best)<0.5 and depth>near_depth):
                closest=ref;best=d2;near_depth=depth
        if closest is not None:
            self.choose(closest)
            self._drag=(closest,event.x,event.y,self.model.vertices[closest].xyz,False)
        else:
            self._drag=None

    def move_vertex_drag(self,event):
        if not self._drag:return
        ref,x0,y0,xyz,wasdrag=self._drag
        step=self._step_if_valid()
        axisindex='XYZ'.index(self.axis.get())
        basis=self._basis()
        unit=[0,0,0];unit[axisindex]=1
        dx_axis=dot(unit,basis[0])*self.scale
        dy_axis=-dot(unit,basis[1])*self.scale
        size=dx_axis**2+dy_axis**2
        if size<0.01:
            self.status.set('Chosen axis is edge-on in this view; orbit camera to edit it.')
            return
        dx=event.x-x0;dy=event.y-y0
        if not wasdrag and (dx*dx+dy*dy)<16:
            return
        delta=(dx*dx_axis+dy*dy_axis)/size
        if step:delta=round(delta/step)*step
        moved=list(xyz);moved[axisindex]=xyz[axisindex]+round(delta)
        try:self.model.set_vertex(ref,moved)
        except ValueError:return
        self._drag=(ref,x0,y0,xyz,True)
        self.update_edit_panel();self.request_view_redraw()
        self.status.set(f'Dragging {self.axis.get()}: {moved[axisindex]}  (commit on mouse release)')

    def _step_if_valid(self):
        try:
            step=int(self.nudge_step.get())
            return step if step>0 else None
        except ValueError:return None

    def finish_vertex_drag(self,event):
        if not self._drag:return
        ref,x0,y0,before,wasdrag=self._drag
        after=self.model.vertices[ref].xyz
        if before!=after:
            self.undo_stack.append((ref,before,after));self.redo_stack=[]
            self.status.set(f'Vertex {ref}: {before} → {after}')
        self._drag=None
        self.update_edit_panel()
        self.finish_view_motion()

    def start_orbit(self,event):
        self._orb=(event.x,event.y,self.azimuth,self.elevation)

    def orbit(self,event):
        if not hasattr(self,'_orb'):return
        x,y,az,el=self._orb
        self.azimuth=az+(event.x-x)*0.008
        self.elevation=max(math.radians(-89),min(math.radians(89),el+(event.y-y)*0.006))
        self.request_view_redraw()

    def start_pan(self,event):
        self._pan=(event.x,event.y,self.pan)

    def pan_view(self,event):
        if not hasattr(self,'_pan'):return
        x,y,pan0=self._pan
        self.pan=(pan0[0]+event.x-x,pan0[1]+event.y-y)
        self.request_view_redraw()

    def wheel_zoom(self,event,delta_override=None):
        delta=event.delta if delta_override is None else delta_override
        factor=1.15 if delta>0 else 1/1.15
        self.zoom=max(0.03,min(200,self.zoom*factor))
        self.request_view_redraw()

    def choose_texture_folder(self):
        directory=filedialog.askdirectory(title='Choose directory containing .MIP files')
        if directory:
            self.texture_folder=Path(directory)
            self.texture_cache.clear()
            self._mip_path_cache.clear()
            self._refresh_texture_info()
            self.redraw()
            self.status.set(f'MIP search directory: {directory}')

    def _choose_mip(self):
        initial=str(self.texture_folder or (self.model.path.parent if self.model else Path.cwd()))
        name=filedialog.askopenfilename(title='Select an ICR2 MIP texture',initialdir=initial,
                            filetypes=[('Papyrus textures','*.mip'),('All files','*.*')])
        if not name:return None
        try:
            self._read_texture(Path(name))
        except (OSError,ValueError,TextureError) as exc:
            messagebox.showerror('Invalid MIP',str(exc))
            return None
        return Path(name)

    def assign_polygon_texture(self):
        if not self.model or self.selected_poly not in self.model.polygons:return
        p=self.model.polygons[self.selected_poly]
        if p.kind!=2:
            messagebox.showwarning('No UV coordinates','This is a plain POLY, not POLY [T].')
            return
        path=self._choose_mip()
        if path:
            self.texture_manual[('polygon',p.offset)]=path
            self._refresh_texture_info();self.redraw()

    def assign_group_texture(self):
        if not self.model or self.selected_poly not in self.model.polygons:return
        p=self.model.polygons[self.selected_poly]
        if p.kind!=2:
            messagebox.showwarning('No UV coordinates','This is a plain POLY, not POLY [T].')
            return
        path=self._choose_mip()
        if path:
            self.texture_manual[('group',p.group)]=path
            self._refresh_texture_info();self.redraw()

    def clear_texture_assignment(self):
        if not self.model or self.selected_poly not in self.model.polygons:return
        p=self.model.polygons[self.selected_poly]
        self.texture_manual.pop(('polygon',p.offset),None)
        self.texture_manual.pop(('group',p.group),None)
        self._refresh_texture_info();self.redraw()

    def _find_named_texture(self,name,*preferred_dirs):
        if not name:return None
        parents=(self.texture_folder, *preferred_dirs,
                 self.model.path.parent if self.model else None,
                 Path(__file__).resolve().parent/'fixtures')
        folders=tuple(dict.fromkeys(Path(folder) for folder in parents if folder is not None))
        key=(name.casefold(),folders)
        if key in self._mip_path_cache:
            return self._mip_path_cache[key]
        wanted=name.casefold()
        names={wanted, wanted+'.mip'}
        match=None
        for folder in folders:
            if not folder.is_dir():continue
            for candidate in folder.iterdir():
                if candidate.is_file() and candidate.name.casefold() in names:
                    match=candidate
                    break
            if match is not None:break
        self._mip_path_cache[key]=match
        return match

    def _texture_path_for(self,p,source_model=None):
        if source_model is not None and source_model is not self.model:
            name=source_model.polygon_materials.get(p.offset)
            return self._find_named_texture(name,source_model.path.parent) if name else None
        if ('polygon',p.offset) in self.texture_manual:
            return self.texture_manual[('polygon',p.offset)]
        if ('group',p.group) in self.texture_manual:
            return self.texture_manual[('group',p.group)]
        if self.appearance and p.kind==2 and self.appearance.texture_name:
            return self._find_named_texture(self.appearance.texture_name,self.appearance.path.parent)
        name=self.model.polygon_materials.get(p.offset) if self.model else None
        if not name:return None
        for parent in (self.texture_folder,self.model.path.parent,
                       self.model.path.parent/'textures',self.model.path.parent/'mip'):
            if parent is None or not parent.is_dir():continue
            for trial in (name,name+'.mip',name+'.MIP'):
                target=parent/trial
                if target.is_file():return target
                if not target.suffix or target.suffix.lower()=='.mip':
                    # DOS texture names may differ only by filename case.
                    matches=list(parent.glob('*'))
                    for file in matches:
                        if file.is_file() and file.name.casefold()==trial.casefold():
                            return file
        return None

    def _read_texture(self,path):
        path=Path(path)
        cached=self.texture_cache.get(path)
        if cached is not None:return cached
        levels=load_mip(path)
        self.texture_cache[path]=levels
        return levels

    def get_polygon_texture(self,p,source_model=None,texture_override=None):
        if not TEXTURE_AVAILABLE or not self.model:return None
        if texture_override:
            path=self._find_named_texture(texture_override,
                              (source_model.path.parent if source_model else None))
        else:
            path=self._texture_path_for(p,source_model)
        if not path:return None
        try:
            return self._read_texture(path)[0]
        except (OSError,ValueError,TextureError) as error:
            # Show the problem in the inspector rather than hiding the model.
            if not hasattr(self,'_texture_errors'):self._texture_errors=set()
            if str(path) not in self._texture_errors:
                self._texture_errors.add(str(path))
                self.status.set(f'MIP preview error: {path.name}: {error}')
            return None

    def _refresh_texture_info(self):
        if not self.model or self.selected_poly not in self.model.polygons:
            self.texture_info.set('Texture: select a polygon');return
        p=self.model.polygons[self.selected_poly]
        if p.kind!=2:
            self.texture_info.set('Plain POLY: no UV coordinates');return
        path=self._texture_path_for(p)
        named=(self.appearance.texture_name if self.appearance else
               self.model.polygon_materials.get(p.offset))
        if path:
            try:
                img=self._read_texture(path)[0]
                self.texture_info.set(f'{path.name}  •  {img.width}×{img.height} pixels  •  group {p.group}')
            except (OSError,ValueError,TextureError) as exc:
                self.texture_info.set(f'Invalid {path.name}: {exc}')
        elif named:
            self.texture_info.set(f'Missing {named}.mip  •  set MIP folder or assign manually')
        else:
            self.texture_info.set(f'No MATERIAL reference  •  group {p.group}; assign MIP manually')

    def _project_textured_polygon(self,p,source_model=None,transform=None):
        """Clip UV attributes together with geometry at the perspective near plane."""
        verts=[]
        source=source_model or self.model
        transform=transform or Transform()
        for ref in p.unique_refs:
            v=source.vertices[ref]
            if v.uv is None:return []
            x,y,z,depth=self._view_coordinates(transform.apply(v.xyz))
            verts.append((x,y,z,depth,float(v.uv[0]),float(v.uv[1])))
        if self.projection.get()=='Perspective (depth)':
            near=self._near_plane();out=[];prev=verts[-1]
            for cur in verts:
                before=prev[2]>=near;inside=cur[2]>=near
                if before!=inside:
                    t=(near-prev[2])/(cur[2]-prev[2])
                    out.append(tuple(prev[i]+t*(cur[i]-prev[i]) for i in range(6)))
                if inside:out.append(cur)
                prev=cur
            verts=out
        mapped=[]
        for x,y,z,d,u,v in verts:
            sx,sy,_=self._screen_from_view(x,y,z,d)
            mapped.append((sx,sy,z if self.projection.get()=='Perspective (depth)' else 1.,u,v))
        return mapped

    def open_palette(self):
        path=filedialog.askopenfilename(title='Open sunny.pcx or 256-color PCX palette',
                                        filetypes=[('PCX palette','*.pcx'),('All files','*.*')])
        if not path:return
        try:
            self.palette=read_pcx_palette(Path(path))
            self.palette_source=f'Loaded: {Path(path).name}'
            self.status.set(f'Loaded palette from {Path(path).name}; MIPs use its RGB colors')
            self.redraw()
        except (OSError,ValueError) as e:
            messagebox.showerror('Palette error',str(e))

    def use_default_palette(self):
        """Restore the palette bundled with the editor after a custom import."""
        path=Path(__file__).with_name('gamepal.pcx')
        try:
            self.palette=read_pcx_palette(path)
            self.palette_source=f'Default: {path.name}'
            self.status.set('Using bundled 256-color game palette')
            self.redraw()
        except (OSError,ValueError) as e:
            messagebox.showerror('Default palette unavailable',str(e))

    def remove_palette(self):
        self.palette=None;self.palette_source='No palette (CAD colors)';self.redraw()

    def show_report(self):
        if not self.model:return
        try:
            _,report=self.model.build_modified_bytes()
        except FormatError as exc:
            messagebox.showerror('Plane computation failed',str(exc))
            return
        text=self.model.summary()+'\n\n'+report.describe()
        dialog=tk.Toplevel(self);dialog.title('FACE / BSP plane rebuild report')
        dialog.geometry('720x520')
        widget=tk.Text(dialog,wrap='word',font=('Consolas',10),padx=10,pady=10)
        widget.pack(fill='both',expand=True)
        widget.insert('1.0',text);widget.configure(state='disabled')
        ttk.Button(dialog,text='Close',command=dialog.destroy).pack(pady=8)

    def save_as(self):
        if not self.model:return
        if not (self.model.dirty or self.imported_pending):
            if not messagebox.askyesno('No changes','No XYZ, UV, color, BSP or DYNAMIC edits. Save an identical copy?'):
                return
        try:
            data,report=self.model.build_modified_bytes()
        except (FormatError,ValueError,OverflowError) as e:
            messagebox.showerror('Cannot save invalid BSP plane',str(e))
            return
        if report.warnings:
            preview='\n'.join(report.warnings[:9])
            if len(report.warnings)>9:
                preview+=f'\n... {len(report.warnings)-9} more (see View → Plane rebuild report)'
            if not messagebox.askyesno('Unresolved FACE/BSP planes',
                                       f'{report.describe().split(chr(10)+chr(10))[0]}\n\n'
                                       f'{preview}\n\nSave the partially rebuilt copy anyway?'):
                return
        source=self.model.path
        out=filedialog.asksaveasfilename(title='Save modified 3DO copy',defaultextension='.3do',
                    initialdir=str(source.parent),initialfile=source.stem+'_edited.3do',
                    filetypes=[('Papyrus 3DO','*.3do')])
        if not out:return
        target=Path(out)
        if target.suffix.lower()!='.3do':
            messagebox.showerror('Choose a .3DO output',
                'Save Copy writes binary .3DO files only. It must not overwrite your editable .3D text.')
            return
        if target.resolve()==source.resolve():
            if not messagebox.askyesno('Overwrite original?',
                  'This is the source 3DO. Overwrite it? A .bak copy will be created first.'):
                return
            backup=target.with_suffix(target.suffix+'.bak')
            if backup.exists():
                if not messagebox.askyesno('Overwrite existing backup?',
                    f'A previous backup already exists:\n\n{backup}\n\n'
                    'Replace it with the current original 3DO before saving?',
                    default='no'):
                    self.status.set('Save canceled; existing backup was preserved.')
                    return
        try:
            checked=write_validated_3do(target,data,
                            expected_vertices=len(self.model.vertices),
                            expected_polygons=len(self.model.polygons),
                            backup=(target.resolve()==source.resolve()))
        except (OSError,FormatError) as e:
            messagebox.showerror('Unable to save / validate',str(e));return
        self.status.set(f'Saved {target.name}: {report.updated_vertices} vertices, {report.updated_planes} planes rebuilt; '
                        f'{report.updated_dynamics} placements; {report.updated_polygon_colors} colors; {len(report.warnings)} warning(s).')
        self.model=checked
        self.imported_pending=False
        # Keep source text/baseline across binary saves so future exports
        # retain human labels and comments. Reset now reads the saved .3DO.
        self.undo_stack=[];self.redo_stack=[]
        self.header.set(target.name)
        self.stats.set(checked.summary().replace('\n','  |  '))
        if self.appearance:self.title(f'ICR2 3DO CAD v1.9 — {target.name} + {self.appearance.path.name}')
        self.poly_order=sorted(checked.polygons)
        self.dynamic_order=sorted(checked.dynamics)
        self.external_model_cache.clear()
        self.refresh_dynamic_list()
        self.refresh_polygon_list()
        self._refresh_polygon_inspector()
        self.update_edit_panel();self.refresh_raw();self.refresh_geometry_targets();self.redraw()
        messagebox.showinfo('Saved',f'Saved {target}\n\n{report.describe()[:2600]}')

    def destroy(self):
        # Cancel outstanding Tk timers before deleting their Tcl callbacks.
        # This matters when GUI regression tests open and close many windows.
        for job in (getattr(self,'_initial_panes_job',None),
                    self._pending_view_redraw,self._pending_refine):
            if job is not None:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        self._pending_view_redraw=None
        self._pending_refine=None
        super().destroy()

    def on_close(self):
        if self.model and (self.model.dirty or self.imported_pending):
            if not messagebox.askyesno('Unsaved 3DO edits',
                'Close without saving your XYZ/UV/BSP changes?'):
                return
        self.destroy()

    def show_help(self):
        messagebox.showinfo('ICR2 3DO CAD v1.9 — Controls',
            'Individual car 3DO files (such as ind96.3do) are wrappers:\n'
            'the MATERIAL node references a MIP and a RECOLOR table.\n'
            'Open one directly to resolve its referenced base geometry, or\n'
            'use File > Load individual car RECOLOR 3DO. The palette slots\n'
            'used by solid polys are remapped for preview; textures use MIPs.\n'
            'This does not change base geometry or save into the wrapper.\n\n'
            'Choose Vertices, Polygons / BSP, Add Geometry, or Raw 3DO tabs.\n'
            'Add Geometry can stage free vertices, create FACE/FACE2 surfaces\n'
            'and choose a specific LIST parent link to preserve existing BSP.\n'
            'Raw 3DO shows read-only record offsets and structural disassembly.\n'
            'LIST insertion does not guarantee camera-dependent occlusion.\n'
            'Existing and newly added polygons can be recolored from the\n'
            'Polygon color control, with optional paired FACE2 recoloring.\n'
            'This edits the base 3DO palette index, not an ind96 RECOLOR file.\n'
            'In polygon mode, left-click a visible polygon or select it in the\n'
            'list. Yellow outline = visible; a dashed hidden outline can be\n'
            'enabled explicitly from the Polygons tab or View menu.\n'
            'Plane list includes the polygon’s ancestor FACE/BSP records.\n'
            'Auto calculate: choose best noncollinear polygon vertices while\n'
            'preserving the source plane orientation. Manual: choose ordered\n'
            'P1,P2,P3 vertices; ordering sets the normal’s direction.\n'
            'Flip orientation: negate all four stored A,B,C,D coefficients.\n'
            'A polygon may have zero or multiple related BSP planes.\n'
            'Edits change only the selected plane, not BSP references/tree.\n\n'
            'Left-click in vertex mode: select an active LOD vertex.\n'
            'Left-drag selected vertex: move along X/Y/Z axis.\n'
            'Right-drag: orbit. Middle-drag: pan. Scroll: zoom.\n'
            '+Y is reversed visually compared with v0.4; raw file coordinates\n'
            'and saved X/Y/Z values are unchanged.\n'
            'Enter XYZ or raw U,V and Apply to edit. UV fields are available only\n'
            'for vertices used by POLY [T]. U,V are unsigned 16-bit integers.\n'
            'Undo/redo works for coordinate and texture UV edits.\n\n'
            'LOD: SWITCH DISTANCE chooses one child subtree using the entered\n'
            'distance in RAW 3DO units. All branches shows overlapping LODs.\n'
            'Projection: Orthographic or Perspective (depth); perspective zoom\n'
            'moves the virtual camera closer/farther; it also affects BSP side.\n'
            'SWITCH DISTANCE threshold remains a separate manual control.\n'
            'LIST entries are painted exactly in their stored back-to-front\n'
            'sequence; depth sorting never changes that order.\n'
            'Lighting is OFF by default; the bundled gamepal.pcx palette is\n'
            'loaded automatically. MIP textures render when supplied.\n'
            'Choose a MIP folder or assign a polygon/group texture in the\n'
            'Polygons tab. Install Pillow and NumPy to enable texture preview.\n\n'
            'BSP: Off shows every polygon in the chosen LOD. Original uses\n'
            'the planes stored in the 3DO. Rebuilt uses safely recomputed planes\n'
            'for edited vertices and retains original coefficients otherwise.\n'
            'FACE and the face branch of BSPF are hidden from the back side.\n'
            'FACE2 selects its front (+) or back (-) child, not both.\n'
            'BSPA/BSPN reorder rather than cull geometry; BSP2 is approximate.\n'
            'BSP mode uses approximate tree order; LIST order is preserved.\n'
            'Selected plane displays its current normal and camera side.\n'
            'A virtual camera on the orbit direction evaluates plane side.\n\n'
            'This is a diagnostic preview, not a pixel-accurate ICR2 renderer.\n'
            'Texture image sampling, arbitrary nested DYNAMIC geometry and\n'
            'complete Papyrus BSP draw order are not implemented. Test in game.\n'
            'When overwriting source 3DO, an existing .bak may also be replaced\n'
            'with confirmation. The new output is validated before replacing.')


def main():
    parser=argparse.ArgumentParser(description='Lightweight editor for existing ICR2 3DO models')
    parser.add_argument('filename',nargs='?',help='Optional input 3DO')
    args=parser.parse_args()
    app=Editor(args.filename)
    app.mainloop()

if __name__=='__main__':
    main()
