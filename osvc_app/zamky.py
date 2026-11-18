"""Zámky souborů pro Linux i Windows (krok I4). Stejné chování jako fcntl.flock: sdílený / výhradní zámek celého souboru,
změna druhu zámku na stejném souboru, neblokující pokus (BlockingIOError), uvolnění i zavřením souboru.
Windows: LockFileEx/UnlockFileEx (sdílené zámky z více souborů vedle sebe, výhradní je vylučuje)."""
import os

if os.name == 'nt':
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_void_p), ('InternalHigh', ctypes.c_void_p), ('Offset', wintypes.DWORD),
                    ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]

    _k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _k32.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
    _k32.LockFileEx.restype = wintypes.BOOL
    _k32.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
    _k32.UnlockFileEx.restype = wintypes.BOOL
    _VYHRADNI, _NECEKAT, _OBSAZENO = 0x2, 0x1, 33   # LOCKFILE_EXCLUSIVE_LOCK, LOCKFILE_FAIL_IMMEDIATELY, ERROR_LOCK_VIOLATION

    def _handle(soubor): return wintypes.HANDLE(msvcrt.get_osfhandle(soubor.fileno()))

    def uvolni(soubor):
        _k32.UnlockFileEx(_handle(soubor), 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(_OVERLAPPED()))   # nezamčený = chyba, nevadí

    def zamkni(soubor, vyhradni=False, necekat=False):
        uvolni(soubor)   # jako flock: změna druhu zámku = uvolnit a zamknout znovu (jinak by se soubor zablokoval sám sobě)
        flags = (_VYHRADNI if vyhradni else 0) | (_NECEKAT if necekat else 0)
        if not _k32.LockFileEx(_handle(soubor), flags, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(_OVERLAPPED())):
            chyba = ctypes.get_last_error()
            if necekat and chyba == _OBSAZENO: raise BlockingIOError('soubor je zamčený')
            raise OSError(chyba, 'zámek souboru nejde získat')
else:
    import fcntl

    def zamkni(soubor, vyhradni=False, necekat=False):
        fcntl.flock(soubor, (fcntl.LOCK_EX if vyhradni else fcntl.LOCK_SH) | (fcntl.LOCK_NB if necekat else 0))

    def uvolni(soubor):
        fcntl.flock(soubor, fcntl.LOCK_UN)


# Bezpečný zápis souborů na Linuxu i ve Windows (I4). Windows: složku nejde otevřít kvůli fsync (zapisuje ji samo) a soubor
# otevřený jen pro čtení nejde fsync; přepsání souboru, který právě drží jiný program (antivirus), se chvíli zkouší znovu.
def zapis_slozku(slozka):
    """Zápis změn ve složce (nové, přejmenované, smazané soubory) na disk; ve Windows nic."""
    if os.name == 'nt': return
    fd = os.open(slozka, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def zapis_soubor(cesta):
    """Zápis hotového souboru na disk (otevřeného pro zápis – Windows jinak hlásí chybu)."""
    with open(cesta, 'r+b') as f: os.fsync(f.fileno())


def nahrad(zdroj, cil, pokusu=40):
    """os.replace; ve Windows při PermissionError (soubor drží jiný program) zkouší znovu až ~4 s."""
    import time
    for i in range(pokusu):
        try: return os.replace(zdroj, cil)
        except PermissionError:
            if os.name != 'nt' or i == pokusu - 1: raise
            time.sleep(0.1)
