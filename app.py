import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from pathlib import Path
import pymupdf  # Updated from fitz
from PIL import Image, ImageOps, ImageFilter
try:
    import pytesseract
except ImportError:
    pytesseract = None

# ---------- Конфигурация OCR ----------
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if pytesseract:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ---------- Логика анализа страниц ----------

def extract_order_number_from_page(page, log_callback=None):
    """
    Ищет номер предписания в верхней половине страницы.
    """
    rect = page.rect
    upper_half_rect = pymupdf.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + rect.height * 0.5)
    
    # 1. Попытка извлечь текстовый слой
    text = page.get_text("text", clip=upper_half_rect)
    pattern = r"АКТ[- ]?ПРЕДПИСАНИЕ\s*(?:ИД\s*)?№\s*(\d+)"
    match = re.search(pattern, text, re.IGNORECASE)
    
    if match:
        return match.group(1)

    # 2. Попытка через OCR
    if pytesseract:
        try:
            mat = pymupdf.Matrix(3, 3)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            width, height = img.size
            img_upper = img.crop((0, 0, width, int(height * 0.5)))
            
            img_gray = img_upper.convert("L")
            img_contrast = ImageOps.autocontrast(img_gray)
            img_binary = img_contrast.point(lambda x: 0 if x < 140 else 255, '1')
            
            ocr_text = pytesseract.image_to_string(img_binary, lang='rus+eng')
            match_ocr = re.search(pattern, ocr_text, re.IGNORECASE)
            if match_ocr:
                return match_ocr.group(1)
        except Exception as e:
            if log_callback:
                log_callback(f"Ошибка OCR на странице: {e}")
    
    return None
    
    return None

def split_pdf_by_order_numbers(input_pdf: str, output_dir: str, start_number: int, log_callback=None):
    input_path = Path(input_pdf)
    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(input_path)
    total_pages = len(doc)

    if log_callback:
        log_callback(f"Всего страниц в файле: {total_pages}")
        log_callback("Анализ страниц на наличие номеров предписаний...")

    # 1. Поиск всех "точек входа" (где начинается новое предписание)
    order_starts = [] # Список кортежей (индекс_страницы, номер_предписания)
    
    for i in range(total_pages):
        page = doc[i]
        num = extract_order_number_from_page(page, log_callback)
        if num:
            order_starts.append((i, num))
            if log_callback:
                log_callback(f"Найдено начало предписания №{num} на стр. {i+1}")

    if not order_starts:
        if log_callback:
            log_callback("Номера предписаний не найдены. Будет создан один файл.")
        # Если ничего не нашли, весь документ — один блок
        order_starts = [(0, None)]

    # 2. Формирование диапазонов страниц
    # Каждый документ длится от своей страницы до начала следующего
    doc_ranges = []
    for idx in range(len(order_starts)):
        start_page = order_starts[idx][0]
        order_num = order_starts[idx][1]
        
        if idx < len(order_starts) - 1:
            end_page = order_starts[idx+1][0] - 1
        else:
            end_page = total_pages - 1
            
        doc_ranges.append({
            'start': start_page,
            'end': end_page,
            'num': order_num
        })

    if log_callback:
        log_callback(f"Итого сформировано блоков: {len(doc_ranges)}")

    # 3. Сохранение блоков
    created_files = []
    for idx, range_info in enumerate(doc_ranges):
        start = range_info['start']
        end = range_info['end']
        num = range_info['num']
        
        if num:
            filename = f"doc_{num}.pdf"
            log_prefix = f"Сохранен №{num}"
        else:
            # Запасной вариант, если первый блок не имеет номера
            doc_num = start_number + idx
            filename = f"doc_{doc_num}.pdf"
            log_prefix = f"Номер не найден, использован порядковый {doc_num}"
            
        out_path = out_dir / filename
        
        try:
            out_doc = pymupdf.open()
            out_doc.insert_pdf(doc, from_page=start, to_page=end)
            out_doc.save(out_path)
            out_doc.close()
            created_files.append(filename)
            if log_callback:
                log_callback(f"{log_prefix}: {filename} (стр. {start+1}–{end+1})")
        except Exception as e:
            if log_callback:
                log_callback(f"Ошибка при сохранении файла {filename}: {e}")

    doc.close()

    if log_callback:
        log_callback(f"\n✅ Готово. Всего создано документов: {len(created_files)}")

    return created_files

# ---------- UI ----------

class GradientCanvas(tk.Canvas):
    def __init__(self, parent, color1="#667eea", color2="#764ba2", **kwargs):
        super().__init__(parent, **kwargs)
        self.color1 = color1
        self.color2 = color2
        self.bind("<Configure>", self._draw_gradient)

    def _draw_gradient(self, event=None):
        self.delete("gradient")
        width = self.winfo_width()
        height = self.winfo_height()
        steps = height
        for i in range(steps):
            ratio = i / steps
            r = int(int(self.color1[1:3], 16) * (1 - ratio) + int(self.color2[1:3], 16) * ratio)
            g = int(int(self.color1[3:5], 16) * (1 - ratio) + int(self.color2[3:5], 16) * ratio)
            b = int(int(self.color1[5:7], 16) * (1 - ratio) + int(self.color2[5:7], 16) * ratio)
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.create_line(0, i, width, i, fill=color, tags="gradient")

def main():
    root = tk.Tk()
    root.title("Разбивка предписаний (По номерам)")
    root.geometry("720x620")

    gradient = GradientCanvas(root, color1="#667eea", color2="#764ba2")
    gradient.pack(fill="both", expand=True)

    card = tk.Frame(gradient, bg="#ffffff", relief="raised", borderwidth=0)
    card.place(relx=0.5, rely=0.5, anchor="center", width=640, height=540)

    title_label = tk.Label(
        card,
        text="Разбивка по номерам предписаний",
        font=("Segoe UI", 16, "bold"),
        bg="#ffffff",
        fg="#4a4a4a"
    )
    title_label.pack(pady=(24, 6))

    subtitle_label = tk.Label(
        card,
        text="Разделителем является новый номер в верхней части страницы",
        font=("Segoe UI", 10),
        bg="#ffffff",
        fg="#666666"
    )
    subtitle_label.pack(pady=(0, 18))

    inner_frame = tk.Frame(card, bg="#ffffff")
    inner_frame.pack(fill="both", expand=True, padx=28, pady=0)

    pdf_label = tk.Label(inner_frame, text="Исходный PDF", font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#444444")
    pdf_label.pack(anchor="w", pady=(8, 4))

    pdf_frame = tk.Frame(inner_frame, bg="#ffffff")
    pdf_frame.pack(fill="x", pady=(0, 10))

    pdf_entry = tk.Entry(pdf_frame, font=("Segoe UI", 11), bg="#fafafa", relief="flat", bd=0)
    pdf_entry.pack(side="left", fill="x", expand=True)

    pdf_btn = tk.Button(pdf_frame, text="Выбрать PDF", font=("Segoe UI", 10), bg="#667eea", fg="#ffffff", relief="flat", padx=12, pady=6, cursor="hand2")
    pdf_btn.pack(side="right", padx=(8, 0))

    dir_label = tk.Label(inner_frame, text="Папка для результатов", font=("Segoe UI", 11, "bold"), bg="#ffffff", fg="#444444")
    dir_label.pack(anchor="w", pady=(8, 4))

    dir_frame = tk.Frame(inner_frame, bg="#ffffff")
    dir_frame.pack(fill="x", pady=(0, 10))

    dir_entry = tk.Entry(dir_frame, font=("Segoe UI", 11), bg="#fafafa", relief="flat", bd=0)
    dir_entry.pack(side="left", fill="x", expand=True)

    dir_btn = tk.Button(dir_frame, text="Выбрать папку", font=("Segoe UI", 10), bg="#667eea", fg="#ffffff", relief="flat", padx=12, pady=6, cursor="hand2")
    dir_btn.pack(side="right", padx=(8, 0))

    split_btn = tk.Button(inner_frame, text="Разбить PDF", font=("Segoe UI", 12, "bold"), bg="#764ba2", fg="#ffffff", relief="flat", padx=16, pady=10, cursor="hand2")
    split_btn.pack(fill="x", pady=(10, 10))

    log_label = tk.Label(inner_frame, text="Лог операций", font=("Segoe UI", 10, "bold"), bg="#ffffff", fg="#444444")
    log_label.pack(anchor="w", pady=(8, 4))

    log_text = scrolledtext.ScrolledText(inner_frame, font=("Consolas", 10), bg="#f7f7fb", fg="#333333", relief="flat", bd=0, wrap="word")
    log_text.pack(fill="both", expand=True, pady=(0, 8))

    def log_msg(msg):
        log_text.insert("end", msg + "\n")
        log_text.see("end")

    def select_pdf():
        path = filedialog.askopenfilename(title="Выберите исходный PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            pdf_entry.delete(0, "end")
            pdf_entry.insert(0, path)

    def select_dir():
        path = filedialog.askdirectory(title="Выберите папку для результатов")
        if path:
            dir_entry.delete(0, "end")
            dir_entry.insert(0, path)

    def run_split():
        log_text.delete("1.0", "end")
        input_pdf = pdf_entry.get().strip()
        output_dir = dir_entry.get().strip()

        if not input_pdf:
            messagebox.showerror("Ошибка", "Не выбран PDF-файл.")
            return
        if not output_dir:
            messagebox.showerror("Ошибка", "Не выбрана папка для результатов.")
            return

        try:
            split_pdf_by_order_numbers(
                input_pdf,
                output_dir,
                start_number=1,
                log_callback=log_msg
            )
            messagebox.showinfo("Готово", "Разбиение завершено успешно.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка:\n{e}")
            log_msg(f"❌ Ошибка: {e}")

    pdf_btn.config(command=select_pdf)
    dir_btn.config(command=select_dir)
    split_btn.config(command=run_split)

    root.mainloop()

if __name__ == "__main__":
    main()
