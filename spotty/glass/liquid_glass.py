"""Жидкое стекло на GLSL (PySide6, других зависимостей нет).

Перенесено из CopyPasta/glass_lab. Отличие в шейдере стекла одно: фаска
преломляет только размытую картинку, без подмеса резкой, и цвет зажат в 0..1
перед умножением на альфу. Внутри:

* VERTEX_SHADER, FRAGMENT_SHADER, COPY_FRAGMENT, BLUR_FRAGMENT — шейдеры;
* GlassParams — настройки;
* OffscreenGlassRenderer — отрисовка в FBO, отдаёт QImage.

Размытие считается в три прохода по уменьшенной копии: копия, гаусс по
горизонтали, гаусс по вертикали. Потом шейдер стекла добавляет преломление на
фаске, подъём насыщенности, подкраску и блик.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import (
    QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat, QVector2D,
    QVector3D, QVector4D,
)
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat, QOpenGLShader,
    QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVertexArrayObject,
)


# Константы GL: PySide6 их не экспортирует, а это обычные числа.
GL_TRIANGLES = 0x0004
GL_COLOR_BUFFER_BIT = 0x4000
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0


# Копия куска источника в уменьшенный буфер — первый шаг размытия.
COPY_FRAGMENT = """
#version 330 core
in vec2 vUv;
out vec4 fragColor;

uniform sampler2D uTex;
uniform vec2 uRes;
uniform vec2 uSrcOrigin;
uniform vec2 uSrcSize;

void main() {
    vec2 p = vUv * uRes;
    fragColor = vec4(texture(uTex, (uSrcOrigin + p) / uSrcSize).rgb, 1.0);
}
"""

# Один проход сепарабельного гаусса. Два таких прохода (по горизонтали и по
# вертикали) дают ровное размытие без зерна — в отличие от выборки по спирали,
# где малое число отсчётов приходится маскировать случайным поворотом.
BLUR_FRAGMENT = """
#version 330 core
in vec2 vUv;
out vec4 fragColor;

uniform sampler2D uTex;
uniform vec2  uTexel;     // шаг в текстурных координатах вдоль прохода
uniform float uSigma;

const int MAX_TAPS = 12;

void main() {
    float sigma = max(uSigma, 0.0001);
    vec3 acc = texture(uTex, vUv).rgb;
    float total = 1.0;
    for (int i = 1; i <= MAX_TAPS; i++) {
        float w = exp(-0.5 * float(i * i) / (sigma * sigma));
        if (w < 0.002) break;
        vec2 offset = uTexel * float(i);
        acc += (texture(uTex, vUv + offset).rgb + texture(uTex, vUv - offset).rgb) * w;
        total += 2.0 * w;
    }
    fragColor = vec4(acc / total, 1.0);
}
"""


VERTEX_SHADER = """
#version 330 core
out vec2 vUv;
void main() {
    // Треугольник на весь экран без буфера вершин: три точки из gl_VertexID.
    vec2 pos = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    vUv = vec2(pos.x, 1.0 - pos.y);   // uv.y = 0 — верх экрана
    gl_Position = vec4(pos * 2.0 - 1.0, 0.0, 1.0);
}
"""

FRAGMENT_SHADER = """
#version 330 core
in vec2 vUv;
out vec4 fragColor;

uniform sampler2D uTex;      // резкий источник
uniform sampler2D uBlurTex;  // он же, заранее размытый, в координатах сцены
uniform vec2  uRes;        // размер сцены в пикселях
uniform vec2  uSrcOrigin;  // где сцена лежит внутри текстуры-источника
uniform vec2  uSrcSize;    // размер текстуры-источника
uniform vec4  uRect;      // x, y, ширина, высота — в пикселях, отсчёт сверху-слева
uniform float uRadius;
uniform float uBlur;
uniform float uBevel;     // ширина фаски, где живёт преломление
uniform float uRefract;   // сила преломления
uniform vec3  uTint;
uniform float uTintAmount;
uniform float uVelocity;  // скорость панели — растягивает блик

// Знаковое расстояние до скруглённого прямоугольника.
float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

// Выборка резкого источника по координате в пикселях сцены. Смещение
// uSrcOrigin позволяет таскать окно по готовому снимку экрана, не пересчитывая
// захват.
vec3 sampleSource(vec2 p) {
    return texture(uTex, (uSrcOrigin + p) / uSrcSize).rgb;
}

// Размытая копия уже посчитана двумя проходами гаусса.
//
// Она лежит в кадровом буфере, а там нулевая строка — нижняя (так устроен GL),
// тогда как p отсчитывается сверху. Без переворота y размытый фон и резкий
// источник читались бы в противоположных системах координат: расхождение
// вылезало ровно на фаске, где к размытию подмешивается резкая картинка.
vec3 sampleBlurred(vec2 p) {
    return texture(uBlurTex, vec2(p.x / uRes.x, 1.0 - p.y / uRes.y)).rgb;
}

void main() {
    vec2 p = vUv * uRes;
    vec2 half_size = uRect.zw * 0.5;
    vec2 center = uRect.xy + half_size;
    vec2 local = p - center;

    float d = sdRoundBox(local, half_size, uRadius);

    if (d > 1.5) {
        // Вне стекла ничего не рисуем: окно там должно быть прозрачным.
        fragColor = vec4(0.0);
        return;
    }

    // Нормаль края — градиент поля расстояний.
    float e = 1.0;
    float dx = sdRoundBox(local + vec2(e, 0.0), half_size, uRadius)
             - sdRoundBox(local - vec2(e, 0.0), half_size, uRadius);
    float dy = sdRoundBox(local + vec2(0.0, e), half_size, uRadius)
             - sdRoundBox(local - vec2(0.0, e), half_size, uRadius);
    vec2 n = normalize(vec2(dx, dy) + 1e-6);

    // t: 0 у самого края, 1 в глубине панели.
    float t = clamp(-d / uBevel, 0.0, 1.0);
    float lens = pow(1.0 - t, 2.5);          // преломление живёт только на фаске

    // Фаска преломляет уже размытую картинку. Резкую сюда не подмешиваем: под
    // тёмной строкой она читалась как несмазанный текст по кромке.
    vec2 refracted = p + n * lens * uRefract;
    vec3 glass = sampleBlurred(refracted);

    // Стекло поднимает насыщенность — иначе размытие выглядит грязным.
    float lum = dot(glass, vec3(0.299, 0.587, 0.114));
    glass = mix(vec3(lum), glass, 1.22);
    glass = mix(glass, uTint, uTintAmount);

    // Блик: свет сверху-слева, живёт на фаске и растягивается при движении.
    vec2 lightDir = normalize(vec2(-0.55, -0.83));
    float facing = clamp(dot(n, lightDir), 0.0, 1.0);
    float spec = pow(facing, 5.0) * lens * (0.42 + uVelocity * 0.5);
    float rim = smoothstep(0.55, 1.0, lens) * 0.10;
    glass += spec + rim;

    // Тонкая тёмная линия у самой кромки — стекло читается объёмным.
    glass *= 1.0 - smoothstep(0.75, 1.0, lens) * 0.12;

    // Альфа со сглаживанием края: окно за пределами стекла прозрачно, поэтому
    // цвет домножаем на альфу — QImage ждёт premultiplied. Подъём насыщенности
    // и блик выводят цвет за 0..1; без clamp на полупрозрачной кромке цвет
    // оказывался больше альфы, и угол расцветал цветными точками.
    float alpha = smoothstep(1.0, -1.0, d);
    fragColor = vec4(clamp(glass, 0.0, 1.0) * alpha, alpha);
}
"""


GLASS_UNIFORMS = ("uTex", "uBlurTex", "uRes", "uSrcOrigin", "uSrcSize", "uRect",
                  "uRadius", "uBlur", "uBevel", "uRefract", "uTint",
                  "uTintAmount", "uVelocity")
COPY_UNIFORMS = ("uTex", "uRes", "uSrcOrigin", "uSrcSize")
BLUR_UNIFORMS = ("uTex", "uTexel", "uSigma")

# Больше 5 при 12 отсчётах гаусс обрезается заметно, поэтому при сильном
# размытии сильнее уменьшаем копию, а не наращиваем число отсчётов.
MAX_SIGMA_PER_LEVEL = 5.0


class GlassParams:
    """Настройки стекла. Значения — в логических пикселях."""

    def __init__(self, radius=26.0, blur=8.0, bevel=26.0, refract=22.0,
                 tint=(0.62, 0.68, 0.86), tint_amount=0.10):
        self.radius = radius
        self.blur = blur
        self.bevel = bevel
        self.refract = refract
        self.tint = tint
        self.tint_amount = tint_amount


class OffscreenGlassRenderer:
    """Свой контекст GL и FBO; ничего не показывает, только считает картинку."""

    def __init__(self):
        self._context: QOpenGLContext | None = None
        self._surface: QOffscreenSurface | None = None
        self._fbo: QOpenGLFramebufferObject | None = None
        self._blur_a: QOpenGLFramebufferObject | None = None
        self._blur_b: QOpenGLFramebufferObject | None = None
        self._programs: dict[str, QOpenGLShaderProgram] = {}
        self._loc: dict[str, dict[str, int]] = {}
        self._vao: QOpenGLVertexArrayObject | None = None
        self._texture: QOpenGLTexture | None = None
        self._source: QImage | None = None
        self._source_dirty = True
        self._failed = False

    # --- инициализация ---

    def _ensure_context(self) -> bool:
        if self._context is not None:
            return True
        if self._failed:
            return False

        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)

        surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        context = QOpenGLContext()
        context.setFormat(fmt)
        if not surface.isValid() or not context.create():
            self._failed = True
            return False

        self._surface, self._context = surface, context
        return True

    def _build_program(self, name: str, fragment: str, uniforms) -> bool:
        program = QOpenGLShaderProgram()
        program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERTEX_SHADER)
        program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fragment)
        if not program.link():
            self._failed = True
            return False
        self._programs[name] = program
        self._loc[name] = {u: program.uniformLocation(u) for u in uniforms}
        return True

    def _ensure_programs(self) -> bool:
        if self._programs:
            return True
        ok = (self._build_program("glass", FRAGMENT_SHADER, GLASS_UNIFORMS)
              and self._build_program("copy", COPY_FRAGMENT, COPY_UNIFORMS)
              and self._build_program("blur", BLUR_FRAGMENT, BLUR_UNIFORMS))
        if not ok:
            return False
        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        return True

    @staticmethod
    def _fit(fbo, size: QSize):
        if fbo is not None and fbo.size() == size:
            return fbo
        return QOpenGLFramebufferObject(size, QOpenGLFramebufferObjectFormat())

    def _ensure_texture(self) -> bool:
        if self._source is None:
            return False
        if self._texture is not None and not self._source_dirty:
            return True
        if self._texture is not None:
            self._texture.destroy()
        # Без мипмапов: картинка рисуется один к одному, а их построение на
        # каждом показе строки стоило бы миллисекунды впустую.
        self._texture = QOpenGLTexture(
            self._source, QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
        self._texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
        self._texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        self._texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self._source_dirty = False
        return True

    # --- использование ---

    def set_source(self, image: QImage) -> None:
        """Картинка, которая лежит под стеклом."""
        self._source = image
        self._source_dirty = True

    def _draw_quad(self, gl) -> None:
        self._vao.bind()
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)
        self._vao.release()

    def _blur_pass(self, gl, size: QSize, sigma: float) -> None:
        """Копия в уменьшенный буфер и два прохода гаусса. Итог — в _blur_a."""
        program = self._programs["blur"]
        loc = self._loc["blur"]

        for source, target, texel in (
            (self._blur_a, self._blur_b, QVector2D(1.0 / size.width(), 0.0)),
            (self._blur_b, self._blur_a, QVector2D(0.0, 1.0 / size.height())),
        ):
            target.bind()
            gl.glViewport(0, 0, size.width(), size.height())
            program.bind()
            gl.glActiveTexture(GL_TEXTURE0)
            gl.glBindTexture(GL_TEXTURE_2D, source.texture())
            program.setUniformValue1i(loc["uTex"], 0)
            program.setUniformValue(loc["uTexel"], texel)
            program.setUniformValue1f(loc["uSigma"], sigma)
            self._draw_quad(gl)
            program.release()
            target.release()

    def render(self, size: QSize, rect: QRectF, params: GlassParams,
               velocity: float = 0.0,
               src_origin: tuple[float, float] = (0.0, 0.0)) -> QImage | None:
        """Отрисовать сцену со стеклянной панелью. None — если GL недоступен.

        src_origin — где сцена лежит внутри источника. Позволяет таскать окно
        по одному снимку экрана, не пересчитывая захват.
        """
        if size.isEmpty() or not self._ensure_context():
            return None
        if not self._context.makeCurrent(self._surface):
            return None
        try:
            if not self._ensure_programs() or not self._ensure_texture():
                return None

            # сигма примерно вдвое меньше видимого радиуса размытия
            sigma = max(params.blur * 0.5, 0.01)
            level = max(1, int(math.ceil(sigma / MAX_SIGMA_PER_LEVEL)))
            small = QSize(max(1, size.width() // level), max(1, size.height() // level))

            self._fbo = self._fit(self._fbo, size)
            self._blur_a = self._fit(self._blur_a, small)
            self._blur_b = self._fit(self._blur_b, small)

            gl = self._context.functions()

            # 1. уменьшенная копия нужного куска источника
            program = self._programs["copy"]
            loc = self._loc["copy"]
            self._blur_a.bind()
            gl.glViewport(0, 0, small.width(), small.height())
            program.bind()
            self._texture.bind(0)
            program.setUniformValue1i(loc["uTex"], 0)
            program.setUniformValue(loc["uRes"],
                                    QVector2D(size.width(), size.height()))
            program.setUniformValue(loc["uSrcOrigin"],
                                    QVector2D(src_origin[0], src_origin[1]))
            program.setUniformValue(loc["uSrcSize"], QVector2D(
                self._source.width(), self._source.height()))
            self._draw_quad(gl)
            program.release()
            self._blur_a.release()

            # 2. два прохода гаусса по уменьшенной копии
            self._blur_pass(gl, small, sigma / level)

            # 3. само стекло
            program = self._programs["glass"]
            loc = self._loc["glass"]
            self._fbo.bind()
            gl.glViewport(0, 0, size.width(), size.height())
            gl.glClearColor(0.0, 0.0, 0.0, 0.0)   # вне стекла — прозрачно
            gl.glClear(GL_COLOR_BUFFER_BIT)
            program.bind()
            self._texture.bind(0)
            gl.glActiveTexture(GL_TEXTURE0 + 1)
            gl.glBindTexture(GL_TEXTURE_2D, self._blur_a.texture())
            gl.glActiveTexture(GL_TEXTURE0)

            # Скаляры только через setUniformValue1f: у обычного setUniformValue
            # целое значение вроде 26.0 уходит в int-перегрузку и до шейдера
            # не доезжает — эффект молча пропадает.
            program.setUniformValue1i(loc["uTex"], 0)
            program.setUniformValue1i(loc["uBlurTex"], 1)
            program.setUniformValue(loc["uRes"],
                                    QVector2D(size.width(), size.height()))
            program.setUniformValue(loc["uSrcOrigin"],
                                    QVector2D(src_origin[0], src_origin[1]))
            program.setUniformValue(loc["uSrcSize"], QVector2D(
                self._source.width(), self._source.height()))
            program.setUniformValue(loc["uRect"], QVector4D(
                rect.x(), rect.y(), rect.width(), rect.height()))
            program.setUniformValue1f(loc["uRadius"], params.radius)
            program.setUniformValue1f(loc["uBlur"], params.blur)
            program.setUniformValue1f(loc["uBevel"], params.bevel)
            program.setUniformValue1f(loc["uRefract"], params.refract)
            program.setUniformValue(loc["uTint"], QVector3D(*params.tint))
            program.setUniformValue1f(loc["uTintAmount"], params.tint_amount)
            program.setUniformValue1f(loc["uVelocity"], velocity)
            self._draw_quad(gl)
            program.release()
            self._fbo.release()
            # Кадровый буфер хранит строки снизу вверх, поэтому переворот при
            # выгрузке нужен — он и стоит по умолчанию.
            return self._fbo.toImage()
        finally:
            self._context.doneCurrent()
