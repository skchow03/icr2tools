"""Independent RGBA tracing-image pass for the 3DO CAD OpenGL viewport.

The image is drawn before the geometry with depth writes disabled, including
in painter/wireframe modes; it cannot change picking, BSP selection or exports.
All OpenGL calls run with the QOpenGLWidget context current on the GUI thread.
"""
from __future__ import annotations

import ctypes

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CLAMP_TO_EDGE, GL_COMPILE_STATUS,
    GL_DEPTH_TEST, GL_DYNAMIC_DRAW, GL_FALSE, GL_FLOAT, GL_FRAGMENT_SHADER,
    GL_LINEAR, GL_LINK_STATUS, GL_MAX_TEXTURE_SIZE, GL_ONE_MINUS_SRC_ALPHA,
    GL_RGBA, GL_RGBA8, GL_SRC_ALPHA, GL_TEXTURE0, GL_TEXTURE2, GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_TRUE, GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE, GL_VERTEX_SHADER,
    glActiveTexture, glAttachShader, glBindBuffer, glBindTexture,
    glBindVertexArray, glBlendFunc, glBufferData, glCompileShader,
    glCreateProgram, glCreateShader, glDeleteBuffers, glDeleteProgram,
    glDeleteShader, glDeleteTextures, glDeleteVertexArrays, glDepthMask,
    glDisable, glDrawArrays, glEnable, glEnableVertexAttribArray,
    glGenBuffers, glGenTextures, glGenVertexArrays, glGetIntegerv,
    glGetProgramInfoLog, glGetProgramiv, glGetShaderInfoLog, glGetShaderiv,
    glGetUniformLocation, glLinkProgram, glPixelStorei, glShaderSource,
    glTexImage2D, glTexParameteri, glUniform1f, glUniform1i,
    glUniformMatrix4fv, glUseProgram, glVertexAttribPointer,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from tracing_reference import plane_vertices


VERTEX = """#version 330 core
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec2 in_uv;
uniform mat4 u_mvp;
out vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(in_position, 1.0);
    v_uv = in_uv;
}
"""

FRAGMENT = """#version 330 core
in vec2 v_uv;
uniform sampler2D u_image;
uniform float u_opacity;
out vec4 frag_color;
void main() {
    vec4 texel = texture(u_image, v_uv);
    frag_color = vec4(texel.rgb, texel.a * u_opacity);
}
"""


class TracingImageGL:
    def __init__(self):
        self._program = None
        self._vao = None
        self._vbo = None
        self._texture = None
        self._image = None
        self._texture_dirty = False
        self._vertex_key = None

    def set_image(self, image):
        """Store a detached QImage; actual texture upload is in paintGL."""
        self._image = image.copy() if image is not None else None
        self._texture_dirty = True
        self._vertex_key = None

    def release(self):
        """Release GL names with the viewport's context current."""
        if self._texture is not None:
            glDeleteTextures(1, [self._texture])
            self._texture = None
        if self._vao is not None:
            glDeleteVertexArrays(1, [self._vao])
            self._vao = None
        if self._vbo is not None:
            glDeleteBuffers(1, [self._vbo])
            self._vbo = None
        if self._program is not None:
            glDeleteProgram(self._program)
            self._program = None
        self._vertex_key = None
        self._texture_dirty = True

    def _prepare_program(self):
        if self._program is not None:
            return
        shaders = []
        program = None
        try:
            for kind, source in ((GL_VERTEX_SHADER, VERTEX),
                                 (GL_FRAGMENT_SHADER, FRAGMENT)):
                sh = glCreateShader(kind)
                shaders.append(sh)
                glShaderSource(sh, source)
                glCompileShader(sh)
                if not glGetShaderiv(sh, GL_COMPILE_STATUS):
                    raise RuntimeError(
                        f"Reference image shader: {glGetShaderInfoLog(sh)}")
            program = glCreateProgram()
            for sh in shaders:
                glAttachShader(program, sh)
            glLinkProgram(program)
            if not glGetProgramiv(program, GL_LINK_STATUS):
                raise RuntimeError(
                    f"Reference image shader link: {glGetProgramInfoLog(program)}")
            vao = int(glGenVertexArrays(1))
            vbo = int(glGenBuffers(1))
            glBindVertexArray(vao)
            glBindBuffer(GL_ARRAY_BUFFER, vbo)
            glBufferData(GL_ARRAY_BUFFER, 6 * 5 * 4, None, GL_DYNAMIC_DRAW)
            glEnableVertexAttribArray(0)
            glVertexAttribPointer(
                0, 3, GL_FLOAT, GL_FALSE, 20, ctypes.c_void_p(0))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(
                1, 2, GL_FLOAT, GL_FALSE, 20, ctypes.c_void_p(12))
            glBindVertexArray(0)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._program, self._vao, self._vbo = program, vao, vbo
            glUseProgram(program)
            glUniform1i(glGetUniformLocation(program, "u_image"), 2)
            glUseProgram(0)
        finally:
            for sh in shaders:
                glDeleteShader(sh)

    def _upload_image(self):
        if not self._texture_dirty:
            return
        if self._texture is not None:
            glDeleteTextures(1, [self._texture])
            self._texture = None
        self._texture_dirty = False
        if self._image is None or self._image.isNull():
            return
        limit = max(1, min(4096, int(glGetIntegerv(GL_MAX_TEXTURE_SIZE))))
        image = self._image
        if image.width() > limit or image.height() > limit:
            image = image.scaled(
                limit, limit,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        rgba = np.frombuffer(
            image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
        self._texture = int(glGenTextures(1))
        glActiveTexture(GL_TEXTURE2)
        glBindTexture(GL_TEXTURE_2D, self._texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(
            GL_TEXTURE_2D, 0, GL_RGBA8, image.width(), image.height(),
            0, GL_RGBA, GL_UNSIGNED_BYTE, rgba)
        glActiveTexture(GL_TEXTURE0)

    def draw(self, reference, projection, view, mesh,
             *, depth_enabled=False, restore_program=None):
        if (reference is None or not reference.visible or
                self._image is None or self._image.isNull() or mesh is None):
            return
        self._prepare_program()
        self._upload_image()
        if self._texture is None:
            return
        key = (reference, tuple(float(v) for v in mesh.center), float(mesh.scale))
        if key != self._vertex_key:
            vertices = plane_vertices(reference, mesh.center, mesh.scale)
            glBindBuffer(GL_ARRAY_BUFFER, self._vbo)
            glBufferData(
                GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_DYNAMIC_DRAW)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            self._vertex_key = key
        mvp = np.ascontiguousarray((projection @ view).T, dtype=np.float32)
        # The reference is a background pass; it contributes no depth and
        # cannot occlude model polygons, selection or vertex picking.
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        try:
            glUseProgram(self._program)
            glUniformMatrix4fv(
                glGetUniformLocation(self._program, "u_mvp"),
                1, GL_FALSE, mvp)
            glUniform1f(
                glGetUniformLocation(self._program, "u_opacity"),
                float(reference.opacity))
            glActiveTexture(GL_TEXTURE2)
            glBindTexture(GL_TEXTURE_2D, self._texture)
            glBindVertexArray(self._vao)
            glDrawArrays(GL_TRIANGLES, 0, 6)
        finally:
            glBindVertexArray(0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glActiveTexture(GL_TEXTURE0)
            glDisable(GL_BLEND)
            glDepthMask(GL_TRUE)
            if depth_enabled:
                glEnable(GL_DEPTH_TEST)
            else:
                glDisable(GL_DEPTH_TEST)
            glUseProgram(restore_program or 0)
