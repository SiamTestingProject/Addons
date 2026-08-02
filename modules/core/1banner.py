import logging
import os

from pystyle import Colors, Write

from modules.core.settings.main_settings import version
from command import my_prefix

logger = logging.getLogger("Zelretch")


def show_banner():
    os.system("cls" if os.name == "nt" else "clear")
    Write.Print(
        f"""
███████╗███████╗██╗     ██████╗ ███████╗████████╗ ██████╗██╗  ██╗
╚══███╔╝██╔════╝██║     ██╔══██╗██╔════╝╚══██╔══╝██╔════╝██║  ██║
  ███╔╝ █████╗  ██║     ██████╔╝█████╗     ██║   ██║     ███████║
 ███╔╝  ██╔══╝  ██║     ██╔══██╗██╔══╝     ██║   ██║     ██╔══██║
███████╗███████╗███████╗██║  ██║███████╗   ██║   ╚██████╗██║  ██║
╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝    ╚═════╝╚═╝  ╚═╝

Developer: Siam Chowdhury
GitHub: https://github.com/ChowdhurySiam
Telegram: @Ch0wdhury_Siam
Version: {version}
Prefix: {my_prefix()}
""",
        Colors.red_to_yellow,
        interval=0,
    )
    logger.info("[LOADER] Loading Zelretch core modules...")


show_banner()
