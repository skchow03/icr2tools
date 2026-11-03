"""OpenGL 3.3 painter-compatible PMP/PMP2 camera-facing billboards.

Only call methods in a current Qt OpenGL context. The decoder/scene builder
runs off-thread; this renderer uploads its validated RG8 index/alpha textures
on the GUI thread and samples the same current PCX palette as the POLY shader.
"""
from __future__ import annotations

import ctypes
import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_STATIC_DRAW, GL_FALSE, GL_FLOAT, GL_TRIANGLES,
    GL_UNSIGNED_BYTE, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER,
    GL_COMPILE_STATUS, GL_LINK_STATUS,
    GL_TEXTURE_2D, GL_TEXTURE0, GL_TEXTURE1, GL_NEAREST, GL_CLAMP_TO_EDGE,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_RG8UI, GL_RG_INTEGER, GL_UNPACK_ALIGNMENT,
    glGenTextures, glDeleteTextures, glActiveTexture, glBindTexture,
    glTexParameteri, glTexImage2D, glPixelStorei,
    glCreateShader, glShaderSource, glCompileShader, glGetShaderiv,
    glGetShaderInfoLog, glCreateProgram, glAttachShader, glLinkProgram,
    glGetProgramiv, glGetProgramInfoLog, glDeleteShader, glDeleteProgram,
    glGetUniformLocation, glUseProgram, glUniform1i, glUniform1f,
    glUniform3f, glUniform4f, glUniformMatrix4fv,
    glGenVertexArrays, glGenBuffers, glBindVertexArray, glBindBuffer,
    glBufferData, glEnableVertexAttribArray, glVertexAttribPointer,
    glDeleteBuffers, glDeleteVertexArrays, glDrawArrays,
)


PMP_VERTEX_SHADER = """
#version 330 core
layout(location=0) in vec2 in_corner;
uniform mat4 u_mvp;
uniform vec3 u_anchor;
uniform vec3 u_right;
uniform vec3 u_up;
uniform float u_pixel_world;
uniform vec4 u_bounds;
out vec2 v_uv;
void main() {
    vec2 point = mix(u_bounds.xy, u_bounds.zw, in_corner);
    vec2 relative = vec2(point.x - 128.0, 128.0 - point.y) * u_pixel_world;
    vec3 world = u_anchor + u_right * relative.x + u_up * relative.y;
    gl_Position = u_mvp * vec4(world, 1.0);
    v_uv = in_corner;
}
"""

PMP_FRAGMENT_SHADER = """
#version 330 core
in vec2 v_uv;
uniform usampler2D u_pmp;
uniform sampler2D u_palette;
out vec4 fragColor;
void main() {
    ivec2 size_px = textureSize(u_pmp, 0);
    ivec2 at = clamp(ivec2(floor(v_uv * vec2(size_px))),
                     ivec2(0), size_px - ivec2(1));
    uvec2 pixel = texelFetch(u_pmp, at, 0).rg;
    if (pixel.g == 0u) discard;
    vec3 rgb = texelFetch(u_palette, ivec2(int(pixel.r), 0), 0).rgb;
    fragColor = vec4(rgb, float(pixel.g) / 255.0);
}
"""


def _program():
    shaders = []
    try:
        for shader_type, source in (
                (GL_VERTEX_SHADER, PMP_VERTEX_SHADER),
                (GL_FRAGMENT_SHADER, PMP_FRAGMENT_SHADER)):
            shader = glCreateShader(shader_type)
            shaders.append(shader)
            glShaderSource(shader, source)
            glCompileShader(shader)
            if not glGetShaderiv(shader, GL_COMPILE_STATUS):
                raise RuntimeError(glGetShaderInfoLog(shader))
        program = glCreateProgram()
        try:
            for shader in shaders:
                glAttachShader(program, shader)
            glLinkProgram(program)
            if not glGetProgramiv(program, GL_LINK_STATUS):
                raise RuntimeError(glGetProgramInfoLog(program))
            return program
        except Exception:
            glDeleteProgram(program)
            raise
    finally:
        for shader in shaders:
            glDeleteShader(shader)


class PMPGLRenderer:
    def __init__(self):
        self.program = _program()
        self.uniforms = {name: glGetUniformLocation(self.program, name)
                         for name in ("u_mvp", "u_anchor", "u_right",
                                      "u_up", "u_pixel_world", "u_bounds")}
        self.vao = int(glGenVertexArrays(1))
        self.vbo = int(glGenBuffers(1))
        # Top-left, bottom-left, bottom-right, top-left, bottom-right, top-right.
        corners = np.ascontiguousarray([
            (0., 0.), (0., 1.), (1., 1.),
            (0., 0.), (1., 1.), (1., 0.)], dtype=np.float32)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, corners.nbytes, corners, GL_STATIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, ctypes.c_void_p(0))
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glUseProgram(self.program)
        glUniform1i(glGetUniformLocation(self.program, "u_pmp"), 0)
        glUniform1i(glGetUniformLocation(self.program, "u_palette"), 1)
        glUseProgram(0)
        self.textures = {}

    def upload(self, resources):
        """Replace only PMP textures, reusing geometry shader/VAO."""
        if self.textures:
            glDeleteTextures(len(self.textures), list(self.textures.values()))
            self.textures.clear()
        if resources is None:
            return
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        for name, image in resources.images.items():
            height, width, bands = image.shape
            if bands != 2 or not (1 <= width <= 256 and 1 <= height <= 256):
                raise ValueError(f"Unexpected PMP bitmap shape: {image.shape}")
            tex = int(glGenTextures(1))
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, tex)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RG8UI, width, height, 0,
                         GL_RG_INTEGER, GL_UNSIGNED_BYTE,
                         np.ascontiguousarray(image))
            self.textures[name] = tex
        glBindTexture(GL_TEXTURE_2D, 0)

    def draw(self, placement, mesh, projection, view, palette_texture):
        """Draw one projected billboard. Returns False if it was not loaded."""
        tex = self.textures.get(placement.image_key)
        if tex is None or not placement.size:
            return False
        center = np.asarray(mesh.center, dtype=np.float64)
        scale = float(mesh.scale)
        xyz = (np.asarray(placement.xyz, dtype=np.float64) - center) / scale
        # Rows of the view matrix are the camera's world right and up
        # vectors, so rotations in DYNAMIC placements affect only the anchor.
        right = np.asarray(view[0, :3], dtype=np.float64)
        up = np.asarray(view[1, :3], dtype=np.float64)
        mvp = np.ascontiguousarray((projection @ view).T, dtype=np.float32)
        bounds = placement.bounds
        glUseProgram(self.program)
        glUniformMatrix4fv(self.uniforms["u_mvp"], 1, GL_FALSE, mvp)
        glUniform3f(self.uniforms["u_anchor"], *map(float, xyz))
        glUniform3f(self.uniforms["u_right"], *map(float, right))
        glUniform3f(self.uniforms["u_up"], *map(float, up))
        glUniform1f(self.uniforms["u_pixel_world"],
                    float(placement.normalized_pixel_size / scale))
        glUniform4f(self.uniforms["u_bounds"], *map(float, bounds))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, tex)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, palette_texture or 0)
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLES, 0, 6)
        glBindVertexArray(0)
        glUseProgram(0)
        return True

    def release(self):
        if self.textures:
            glDeleteTextures(len(self.textures), list(self.textures.values()))
            self.textures.clear()
        if self.vao:
            glDeleteVertexArrays(1, [self.vao])
            self.vao = None
        if self.vbo:
            glDeleteBuffers(1, [self.vbo])
            self.vbo = None
        if self.program:
            glDeleteProgram(self.program)
            self.program = None
