"""
Светлая у панели задач тема или тёмная (перенесено из Knack).

Значок в трее рисуется одним цветом, и белый на светлой панели задач попросту
исчезает. Windows держит для панели задач отдельную настройку —
`SystemUsesLightTheme`, она не совпадает с темой приложений.
"""

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def taskbar_is_light():
    """True — панель задач светлая, значок нужно рисовать тёмным."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            value, _type = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        return bool(value)
    except OSError:
        return False        # тёмная тема — значение по умолчанию у Windows 10/11


def tray_ink():
    """Цвет значка в трее под текущую тему."""
    return "#1A1A1A" if taskbar_is_light() else "#FFFFFF"
