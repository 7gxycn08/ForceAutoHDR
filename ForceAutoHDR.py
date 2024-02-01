import os.path
import threading
import winreg
import customtkinter
from tkinter import messagebox, filedialog
import ctypes
from PIL import Image

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except AttributeError:
    ctypes.windll.user32.SetProcessDPIAware(True)


def add_exe_to_reg():
    global keys_drop
    exe_path = filedialog.askopenfilename(title="Select EXE", filetypes=[("Executable files", "*.exe")])
    exe_name = os.path.basename(exe_path)
    if exe_name == "":
        messagebox.showerror(title="Error.", message="Select EXE to Add.")
        return
    base_path = r"Software\Microsoft\Direct3D"
    key_name = exe_name.rstrip('.exe')
    registry_path = fr"{base_path}\{key_name}"
    key = None
    try:
        (winreg.CreateKey
         (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Direct3D"))
        (winreg.CreateKey
         (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Direct3D\D3DBehaviors"))
        (winreg.CreateKey
         (winreg.HKEY_LOCAL_MACHINE, fr"Software\Microsoft\Direct3D\{key_name}"))

        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry_path, 0, winreg.KEY_SET_VALUE)

        value_name_str = key_name
        winreg.SetValueEx(key, value_name_str, 0, winreg.REG_SZ, f"{key_name}.exe")

        value_name_str = "D3DBehaviors"
        winreg.SetValueEx(key, value_name_str, 0, winreg.REG_SZ,
                          "BufferUpgradeOverride=1;BufferUpgradeEnable10Bit=1")

        messagebox.showinfo(title="Done.", message="EXE Name Added to Registry.")
        keys_drop.configure(values=show_Keys())
        try:
            keys_drop.set(value=show_Keys()[0])
        except:
            keys_drop.set(value="No Games Found")

    except OSError as e:
        messagebox.showerror(title="Error", message=f"Error creating registry key: {e}")
        if e.winerror == 87:
            messagebox.showerror(title="Error",
                                 message=
                                 "The parameter might be incorrect. "
                                 "Check if the registry path follows the expected format.")
            messagebox.showerror(title="Error", message=f"Registry Path: {registry_path}")
        else:
            messagebox.showerror(title="Error", message="Unexpected error.")
    finally:
        if key is not None:
            winreg.CloseKey(key)


def show_list_in_message_box(mylist):
    message = '\n'.join(map(str, mylist))
    messagebox.showinfo("AutoHDR Forced", message)


def show_Keys():
    path = r"Software\Microsoft\Direct3D"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            index = 0
            keys = []
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, index)
                    keys.append(subkey_name)
                    index += 1
                except OSError:
                    break
    except FileNotFoundError:
        messagebox.showerror(title="Error", message=f"Registry path not found: {path}")
        keys = []
    except OSError as os_exception:
        messagebox.showerror(title="Error", message=f"Error accessing registry: {os_exception}")
        keys = []
    return keys


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def delete_registry_key(key_name):
    global keys_drop
    path = r"Software\Microsoft\Direct3D"
    i = messagebox.askyesno(title="Warning.",
                            message=f"Are you sure you want to delete key in path: {path}\\{key_name}")
    if i == False:
        return
    else:
        try:
            if is_admin():
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteKey(key, key_name)
                    messagebox.showinfo(title="Done.",
                                        message=f"Registry key '{key_name}' in path '{path}' deleted successfully.")
                    keys_drop.configure(values=show_Keys())
                    try:
                        keys_drop.set(value=show_Keys()[0])
                    except:
                        keys_drop.set(value="No Games Found")

            else:
                messagebox.showerror(title="Error",
                                     message="Run the script with administrator privileges to modify the registry.")
        except FileNotFoundError:
            messagebox.showerror(title="Error", message=fr"Registry path not found: {path}/{key_name}")
        except PermissionError:
            (messagebox.showerror
             (title="Error",
              message=f"Permission error: Unable to delete key in '{path}'. Ensure you have sufficient privileges."))


def do_popup(event, frame):
    try:
        frame.tk_popup(event.x_root, event.y_root)
    finally:
        frame.grab_release()


customtkinter.set_appearance_mode("light")  # Modes: Computer (default), light, dark
customtkinter.set_default_color_theme("dark-blue")  # Themes: blue (default), dark-blue, green

app = customtkinter.CTk()
app.geometry("400x240")
app.title("ForceAutoHDR")
app.iconbitmap(r"Resources\hdr.ico")
blank_image = Image.new('RGB', (1, 1))

keys_drop = customtkinter.CTkOptionMenu(master=app, values=show_Keys())

try:
    keys_drop.set(value=show_Keys()[0])
except:
    keys_drop.set(value="No Games Found")

keys_drop.place(relx=0.5, rely=0.2, anchor=customtkinter.CENTER)
add_button = customtkinter.CTkButton(master=app, text="Add Game EXE",
                                     command=
                                     lambda: threading.Thread(target=lambda: add_exe_to_reg(),
                                                              daemon=True).start())
add_button.place(relx=0.5, rely=0.65, anchor=customtkinter.CENTER)
delete_button = customtkinter.CTkButton(master=app, text="Delete Game EXE",
                                        command=
                                        lambda: threading.Thread(
                                            target=lambda: delete_registry_key(keys_drop.get()),
                                            daemon=True).start())
delete_button.place(relx=0.5, rely=0.80, anchor=customtkinter.CENTER)
app.mainloop()
