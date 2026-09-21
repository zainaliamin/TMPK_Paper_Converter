import base64
import os
import shutil
import sys
import threading
import time
import tempfile
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import Tk, Label, filedialog, messagebox, StringVar, ttk, scrolledtext

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait

def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def first_existing_path(paths):
    for path in paths:
        if path and path.exists():
            return path
    return None


def debug_log_path() -> Path:
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop / "Paper Generator debug.log"
    return Path(tempfile.gettempdir()) / "Paper Generator debug.log"


def append_debug_log(text: str):
    try:
        with debug_log_path().open("a", encoding="utf-8") as log_file:
            log_file.write(text.rstrip() + "\n")
    except Exception:
        pass


def image_to_data_url(image_path: Path) -> str:
    ext = image_path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    elif ext == "svg":
        ext = "svg+xml"
    mime = f"image/{ext}"
    data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"



class PaperBatchTool:
    def __init__(self, root):
        self.root = root
        self.root.title("Paper Batch Tool")
        self.root.configure(bg="#f9fafb")
        self.root.state("zoomed")
        self.root.minsize(1200, 720)
        self._setup_theme()

        self.folder_path = None  # type: Path | None
        self.logo_path = None    # type: Path | None
        self.folder_display = StringVar(value="No folder selected")
        self.logo_display = StringVar(value="No logo selected")
        self.progress_var = tk.DoubleVar(value=0.0)
        self._chrome_profile_dir = None

        # --- Layout containers ---
        main = ttk.Frame(root, padding=(24, 24, 24, 24), style="Card.TFrame")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=3, uniform="cols")
        main.columnconfigure(1, weight=2, uniform="cols")

        left = ttk.Frame(main, padding=20, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(main, padding=20, style="Panel.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))

        # --- Left column: inputs ---
        header = ttk.Frame(left, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="w")
        Label(header, text="Paper Batch Tool", bg="#f9fafb", fg="#111827", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        Label(header, text="Update school names and logos across multiple papers in one go.", bg="#f9fafb", fg="#4b5563", font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", pady=(4, 12))

        # Folder
        folder_frame = ttk.Frame(left, style="Card.TFrame")
        folder_frame.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        folder_frame.columnconfigure(1, weight=1)
        Label(folder_frame, text="Select Folder", bg="#ffffff", fg="#111827", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        Label(folder_frame, text="Choose folder containing HTML/HTM files.", bg="#ffffff", fg="#6b7280", font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=2, sticky="w")
        self.folder_entry = ttk.Entry(folder_frame, textvariable=self.folder_display, state="readonly", style="Modern.TEntry")
        self.folder_entry.grid(row=2, column=0, sticky="ew", pady=(6, 4))
        ttk.Button(folder_frame, text="Browse", command=self.choose_folder, style="Primary.TButton").grid(row=2, column=1, padx=(8, 0), sticky="ew")

        # School name
        school_frame = ttk.Frame(left, style="Card.TFrame")
        school_frame.grid(row=2, column=0, sticky="ew", pady=(10, 6))
        Label(school_frame, text="New School Name", bg="#ffffff", fg="#111827", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.new_name_entry = ttk.Entry(school_frame, width=50, style="Modern.TEntry")
        self.new_name_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # Logo
        logo_frame = ttk.Frame(left, style="Card.TFrame")
        logo_frame.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        logo_frame.columnconfigure(1, weight=1)
        Label(logo_frame, text="New Logo Image", bg="#ffffff", fg="#111827", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        Label(logo_frame, text="PNG/JPG etc., will replace <img id='mn_logo'> image.", bg="#ffffff", fg="#6b7280", font=("Segoe UI", 10)).grid(row=1, column=0, columnspan=2, sticky="w")
        self.logo_preview = Label(logo_frame, text="Preview", bg="#ffffff", fg="#6b7280", width=10, height=5, relief="solid", bd=1, highlightthickness=1, highlightbackground="#D4D7DD")
        self.logo_preview.grid(row=2, column=0, sticky="w", pady=(6, 4))
        self.logo_entry = ttk.Entry(logo_frame, textvariable=self.logo_display, state="readonly", style="Modern.TEntry")
        self.logo_entry.grid(row=2, column=1, sticky="ew", pady=(6, 4))
        ttk.Button(logo_frame, text="Browse", command=self.choose_logo, style="Primary.TButton").grid(row=2, column=2, padx=(8, 0), sticky="ew")

        # Run button
        self.run_button = ttk.Button(left, text="Run Batch Process", command=self.run, style="Primary.TButton")
        self.run_button.grid(row=4, column=0, sticky="ew", pady=(16, 8))

        self.status_label = Label(left, text="", anchor="w", bg="#f9fafb", fg="#6b7280", font=("Segoe UI", 10))
        self.status_label.grid(row=5, column=0, sticky="w")

        # --- Right column: status + log ---
        right.rowconfigure(3, weight=1)
        header_right = ttk.Frame(right, style="Card.TFrame")
        header_right.grid(row=0, column=0, sticky="ew")
        header_right.columnconfigure(0, weight=1)
        Label(header_right, text="Batch Status", bg="#f3f4f6", fg="#111827", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.status_badge = Label(header_right, text="Idle", bg="#e5e7eb", fg="#374151", font=("Segoe UI", 9, "bold"), padx=10, pady=4)
        self.status_badge.grid(row=0, column=1, sticky="e")

        self.progress_bar = ttk.Progressbar(right, variable=self.progress_var, maximum=100, style="Accent.Horizontal.TProgressbar")
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        self.progress_text = Label(right, text="Idle", bg="#f3f4f6", fg="#4b5563", font=("Segoe UI", 10))
        self.progress_text.grid(row=2, column=0, sticky="w")

        self.log_widget = scrolledtext.ScrolledText(
            right,
            height=12,
            bg="#f8fafc",
            fg="#111827",
            insertbackground="#111827",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#D0D7E2",
            highlightcolor="#2D6CDF",
            font=("Consolas", 10),
            wrap="word",
        )
        self.log_widget.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        self.log_widget.config(state="disabled")

    # ---------- UI handlers ----------

    def choose_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.folder_path = Path(path)
            self.folder_display.set(str(self.folder_path))

    def choose_logo(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Image files", "*.png;*.jpg;*.jpeg;*.gif;*.bmp"),
                ("All files", "*.*"),
            ]
        )
        if path:
            self.logo_path = Path(path)
            self.logo_display.set(str(self.logo_path))
            self.logo_preview.config(text=self.logo_path.name)

    def run(self):
        if getattr(self, "_running", False):
            return
        # Basic checks
        if not self.folder_path:
            messagebox.showerror(
                "Error", "Please select the folder with HTML/HTM files."
            )
            return

        new_name = self.new_name_entry.get().strip()
        if not new_name:
            messagebox.showerror("Error", "Please enter the new school name.")
            return

        if not self.logo_path or not self.logo_path.exists():
            messagebox.showerror("Error", "Please select a valid new logo image.")
            return

        self._running = True
        self.run_button.config(state="disabled")
        self._set_processing(True)
        self._set_status("Starting...")

        threading.Thread(
            target=self._run_worker,
            args=(new_name,),
            daemon=True,
        ).start()

    def _run_worker(self, new_name: str):
        try:
            # Find all .htm / .html files (including subfolders)
            html_files = list(self.folder_path.rglob("*.htm")) + list(
                self.folder_path.rglob("*.html")
            )
            if not html_files:
                self._ui(lambda: messagebox.showerror(
                    "Error", "No .htm or .html files found in the selected folder."
                ))
                return

            # Create sibling PDF output folder
            parent = self.folder_path.parent
            folder_name = self.folder_path.name
            pdf_folder = parent / f"{folder_name}_pdf"
            pdf_folder.mkdir(exist_ok=True)

            # Prepare logo data URL once for the batch
            logo_data_url = None
            if self.logo_path and self.logo_path.exists():
                try:
                    logo_data_url = image_to_data_url(self.logo_path)
                except Exception as e:
                    print(f"Failed to read logo image: {e}")

            pdf_count = 0

            try:
                driver = self._create_driver()
            except Exception as e:
                append_debug_log(traceback.format_exc())
                self._cleanup_chrome_profile()
                log_path = debug_log_path()
                self._ui(lambda: messagebox.showerror(
                    "Error",
                    f"Failed to start ChromeDriver:\n{e}\n\n"
                    f"Debug log saved at:\n{log_path}",
                ))
                return

            try:
                total = len(html_files)
                processed = 0
                self._set_progress(processed, total)
                for idx, html_file in enumerate(html_files, start=1):
                    self._set_status(f"Processing {idx}/{total}: {html_file.name}")
                    try:
                        pdf_created = self.export_to_pdf_with_js(
                            html_file, pdf_folder, driver, new_name, logo_data_url
                        )
                        if pdf_created:
                            pdf_count += 1
                        processed += 1
                        self._set_progress(processed, total)
                    except Exception as e:
                        print(f"Error processing {html_file}: {e}")
                self._ui(lambda: messagebox.showinfo(
                    "Done",
                    f"HTML files found: {len(html_files)}\n"
                    f"PDFs created: {pdf_count}\n\n"
                    f"PDF folder:\n{pdf_folder}",
                ))
            finally:
                driver.quit()
                self._cleanup_chrome_profile()
        finally:
            self._running = False
            self._ui(lambda: self.run_button.config(state="normal"))
            self._set_status("")
            self._set_processing(False)

    # ---------- Core logic: change name & logo ----------

    def process_html_file(self, html_path: Path, new_name: str) -> bool:
        """
        Change school name in <h4 class='school_name_h3'>
        and logo in <img id='mn_logo'> for one HTML file.
        Returns True if any change was made.
        """
        html_text = html_path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html_text, "lxml")

        changed = False

        # --- Update school name ---
        h4_tag = soup.find("h4", class_="school_name_h3")
        if h4_tag:
            h4_tag.clear()
            h4_tag.append(new_name)
            changed = True
            print(f"  School name updated in: {html_path.name}")
        else:
            print(f"  No <h4 class='school_name_h3'> found in: {html_path.name}")

        # --- Update logo image ---
        img_tag = soup.find("img", id="mn_logo")
        if img_tag:
            src = img_tag.get("src", "")
            if src:
                print(f"  Found logo src '{src}' in {html_path.name}")
                html_dir = html_path.parent
                logo_file_path = (html_dir / src).resolve()
                logo_file_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(self.logo_path, logo_file_path)
                changed = True
                print(f"  Logo replaced at: {logo_file_path}")
        else:
            print(f"  No <img id='mn_logo'> found in: {html_path.name}")

        if changed:
            html_path.write_text(str(soup), encoding="utf-8")

        return changed

    # ---------- Core logic: export to PDF using page JS ----------

    def export_to_pdf_with_js(
        self, html_path: Path, pdf_folder: Path, driver, new_name: str, logo_data_url: str | None
    ) -> bool:
        """
        Use Selenium + Chrome DevTools to:
        - open the HTML in headless Chrome/Chromium
        - update school name and logo directly via DOM
        - heal DOM if heading was previously split
        - generate a PDF of the resulting layout
        """
        rel_path = html_path.relative_to(self.folder_path)
        pdf_path = (pdf_folder / rel_path).with_suffix(".pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._selenium_export(driver, html_path, pdf_path, new_name, logo_data_url)
            return pdf_path.exists()
        except Exception as e:
            print(f"  Failed to create PDF for {html_path}: {e}")
            return False

    def _create_driver(self):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--remote-debugging-port=0")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-features=RendererCodeIntegrity")
        self._chrome_profile_dir = tempfile.mkdtemp(prefix="paper-tool-chrome-")
        options.add_argument(f"--user-data-dir={self._chrome_profile_dir}")

        base_dir = app_base_dir()
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        chrome_path = first_existing_path([
            base_dir / "chrome-win64" / "chrome.exe",
            Path(__file__).resolve().parent / "chrome-win64" / "chrome.exe" if not getattr(sys, "frozen", False) else None,
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe" if local_app_data else None,
        ])
        if chrome_path:
            options.binary_location = str(chrome_path)

        driver_path = first_existing_path([
            base_dir / "chromedriver.exe",
            Path(__file__).resolve().parent / "chromedriver.exe" if not getattr(sys, "frozen", False) else None,
        ])
        append_debug_log(
            "\n".join([
                "",
                "=== ChromeDriver startup ===",
                f"frozen: {getattr(sys, 'frozen', False)}",
                f"base_dir: {base_dir}",
                f"chrome_path: {chrome_path}",
                f"driver_path: {driver_path}",
                f"profile_dir: {self._chrome_profile_dir}",
            ])
        )
        if not chrome_path:
            raise RuntimeError(f"Chrome was not found. Expected bundled Chrome in {base_dir / 'chrome-win64' / 'chrome.exe'}")
        if not driver_path:
            raise RuntimeError(f"ChromeDriver was not found. Expected bundled driver in {base_dir / 'chromedriver.exe'}")

        service = ChromeService(executable_path=str(driver_path)) if driver_path else ChromeService()
        return webdriver.Chrome(service=service, options=options)

    def _cleanup_chrome_profile(self):
        if self._chrome_profile_dir:
            shutil.rmtree(self._chrome_profile_dir, ignore_errors=True)
            self._chrome_profile_dir = None

    def _set_status(self, text: str):
        # Schedule status updates on the main thread
        self._ui(lambda: self.status_label.config(text=text))
        self._log(text)

    def _ui(self, func):
        self.root.after(0, func)

    def _set_progress(self, processed: int, total: int):
        if total <= 0:
            return
        percent = round((processed / total) * 100, 1)
        self._ui(lambda: self.progress_var.set(percent))
        self._ui(lambda: self.progress_text.config(text=f"{processed}/{total} files - {percent}%"))

    def _log(self, text: str):
        def inner():
            self.log_widget.config(state="normal")
            self.log_widget.insert("end", text + "\n")
            self.log_widget.see("end")
            self.log_widget.config(state="disabled")
        self._ui(inner)

    def _set_processing(self, processing: bool):
        def inner():
            if processing:
                self.status_badge.config(text="Processing", bg="#c7d2fe", fg="#1f2937")
            else:
                self.status_badge.config(text="Idle", bg="#e5e7eb", fg="#374151")
        self._ui(inner)

    def _selenium_export(
        self, driver, html_path: Path, pdf_path: Path, new_name: str, logo_data_url: str | None
    ):
        file_url = "file:///" + str(html_path.resolve()).replace("\\", "/")
        print(f"  [selenium] Opening {file_url}")
        driver.get(file_url)

        WebDriverWait(driver, 15).until(
            lambda current_driver: current_driver.execute_script("return document.readyState") == "complete"
        )

        # Apply print media so @media print rules hide toolbars
        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"media": "print"})

        # Update school name, logo, and heal headings in the live DOM
        driver.execute_script(
            """
            (function(newName, logoDataUrl) {
                // 1. Update school name across all header variations
                var nameSelectors = [
                    '.school_name_h3',
                    '#school_name_h3',
                    'h3.school_name_h3',
                    'h4.school_name_h3',
                    'h6.school_name_h3'
                ];
                nameSelectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        el.textContent = newName;
                    });
                });

                // 2. Update logo and watermark across all image elements
                if (logoDataUrl) {
                    document.querySelectorAll('#mn_logo, #watermarkLogo img').forEach(function(img) {
                        img.src = logoDataUrl;
                    });
                }



                // 4. Hide toolbar and print buttons
                window.dispatchEvent(new Event('beforeprint'));

                var style = document.getElementById('__paper_generator_print_style');
                if (!style) {
                    style = document.createElement('style');
                    style.id = '__paper_generator_print_style';
                    document.head.appendChild(style);
                }
                style.textContent = [
                    'button, .btn, .toolbar, .top-buttons, #print { display: none !important; }',
                    '@media print { button, .btn, .toolbar, .top-buttons, #print { display: none !important; } }'
                ].join('\\n');

                var selectors = ['button', '.btn', '.toolbar', '.top-buttons', '#print'];
                selectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        el.dataset._origDisplay = el.style.display;
                        el.style.display = 'none';
                    });
                });
            })(arguments[0], arguments[1]);
            """,
            new_name,
            logo_data_url,
        )

        # Short pause for layout changes
        time.sleep(0.8)

        # Use Chrome DevTools printToPDF
        pdf_data = driver.execute_cdp_cmd(
            "Page.printToPDF",
            {"printBackground": True, "preferCSSPageSize": True},
        )
        pdf_bytes = base64.b64decode(pdf_data["data"])
        pdf_path.write_bytes(pdf_bytes)
        print(f"  [selenium] PDF saved to {pdf_path}")

    def _setup_theme(self):
        # ttk theme tweaks for light UI
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Card.TFrame", background="#ffffff", borderwidth=0)
        style.configure("Panel.TFrame", background="#f3f4f6", borderwidth=1, relief="solid")
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor="#e5e7eb",
            background="#2563eb",
            darkcolor="#1d4ed8",
            lightcolor="#3b82f6",
            bordercolor="#e5e7eb",
            thickness=8,
        )
        style.configure(
            "Primary.TButton",
            background="#2563eb",
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=3,
            focuscolor="#2D6CDF",
            padding=(12, 8),
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#1d4ed8"), ("pressed", "#1d4ed8")],
            relief=[("pressed", "flat"), ("active", "flat")],
        )
        style.configure(
            "Modern.TEntry",
            fieldbackground="#ffffff",
            bordercolor="#D0D7E2",
            lightcolor="#D0D7E2",
            darkcolor="#D0D7E2",
            foreground="#111827",
            padding=(10, 6),
            relief="flat",
        )
        style.map(
            "Modern.TEntry",
            bordercolor=[("focus", "#2D6CDF"), ("!focus", "#D0D7E2")],
            lightcolor=[("focus", "#2D6CDF"), ("!focus", "#D0D7E2")],
            darkcolor=[("focus", "#2D6CDF"), ("!focus", "#D0D7E2")],
        )


def main():
    root = Tk()
    app = PaperBatchTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
