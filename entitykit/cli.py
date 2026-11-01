"""entitykit komut satırı: entitykit <salience|gain|graph> [girdi] [seçenekler].

Alt komut, ilgili modülün main()'ine gider. İlk konumsal argüman girdi
seçeneğine çevrilir: yerel yol --file/--files, http(s) adresi --url/--urls olur.
Diğer seçenekler olduğu gibi geçer; tek doğruluk kaynağı modüllerin argparse'ıdır.
"""
import importlib
import sys

from . import __version__

# alt komut: (modül, yerel girdi seçeneği, URL girdi seçeneği, kısa açıklama)
COMMANDS = {
    "salience": ("entity_salience", "--file", "--url",
                 "varlıklar, salience ve sorgu kapsaması"),
    "gain": ("info_gain", "--file", "--url",
             "rakiplere karşı kopya ve özgün cümleler"),
    "graph": ("topical_graph", "--files", "--urls",
              "sayfa grubunun varlık ağı ve hedefteki eksikler"),
}

USAGE = "\n".join(
    ["kullanım: entitykit <komut> [girdi] [seçenekler]", "", "komutlar:"]
    + [f"  {c:<9} {d}" for c, (_, _, _, d) in COMMANDS.items()]
    + ["", "Bir komutun seçenekleri için: entitykit <komut> --help",
       "Sürüm: entitykit --version"])


def translate(cmd, args):
    """İlk konumsal argümanları alt komutun girdi seçeneğine çevirir.

    graph birden çok yol alabilir: kabuk "*.md" desenini açmışsa baştaki tüm
    konumsal argümanlar tek --files değerinde birleşir.
    """
    _, local, remote, _ = COMMANDS[cmd]
    n = 0
    while n < len(args) and not args[n].startswith("-"):
        n += 1
        if cmd != "graph":
            break
    if not n:
        return list(args)
    inputs = args[:n]
    flag = remote if inputs[0].startswith(("http://", "https://")) else local
    joiner = "," if flag == remote else " "
    return [flag, joiner.join(inputs)] + list(args[n:])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if argv[0] == "--version":
        print(f"entitykit {__version__}")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"HATA: bilinmeyen komut: {cmd}\n\n{USAGE}", file=sys.stderr)
        return 2
    module = importlib.import_module(f".{COMMANDS[cmd][0]}", __package__)
    module.main(translate(cmd, rest))
    return 0
