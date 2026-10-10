"""OpenGL 函数绑定层。

PyQt5 的 QOpenGLContext 没有 PySide2 那样的 functions() 方法，也没有内置
PyOpenGL，因此这里用 ctypes 直接绑定系统 opengl32.dll，向 scene/viewport.py
提供 f.glXxx(...) / f.GL_XXX 形式的调用接口（这些接口都是 OpenGL 1.1 函数，
opengl32.dll 直接导出并转发到当前线程的 GL 上下文）。
"""
import ctypes

_gl = ctypes.WinDLL("opengl32.dll")


def _bind(name, argtypes):
    fn = getattr(_gl, name)
    fn.argtypes = argtypes
    fn.restype = None
    return fn


glEnable = _bind("glEnable", [ctypes.c_uint])
glDisable = _bind("glDisable", [ctypes.c_uint])
glClear = _bind("glClear", [ctypes.c_uint])
glClearColor = _bind("glClearColor", [ctypes.c_float] * 4)
glBlendFunc = _bind("glBlendFunc", [ctypes.c_uint, ctypes.c_uint])
glDepthMask = _bind("glDepthMask", [ctypes.c_ubyte])

_gl.glGetError.restype = ctypes.c_uint
_gl.glGetError.argtypes = []
glGetError = _gl.glGetError

_glDrawArrays = _bind("glDrawArrays", [ctypes.c_uint, ctypes.c_int, ctypes.c_int])
_glDrawElements = _bind("glDrawElements",
                        [ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p])


def glDrawArrays(mode, first, count):
    _glDrawArrays(int(mode), int(first), int(count))


def glDrawElements(mode, count, type_, indices):
    if hasattr(indices, "ctypes"):
        ptr = ctypes.c_void_p(indices.ctypes.data)
    elif indices is None:
        ptr = ctypes.c_void_p(0)
    else:
        ptr = ctypes.c_void_p(int(indices))
    _glDrawElements(int(mode), int(count), int(type_), ptr)


GL_DEPTH_TEST = 0x0B71
GL_MULTISAMPLE = 0x809D
GL_PROGRAM_POINT_SIZE = 0x8642
GL_BLEND = 0x0BE2
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_ONE = 0x0001
GL_POINTS = 0x0000
GL_LINES = 0x0001
GL_LINE_STRIP = 0x0003
GL_TRIANGLES = 0x0004
GL_UNSIGNED_INT = 0x1405
