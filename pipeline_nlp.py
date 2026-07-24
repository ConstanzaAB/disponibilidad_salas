import json
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class BibliotecaMagnoliaPipeline:
    def __init__(self, target_url):
        self.target_url = target_url

    def fetch_and_extract(self):
        if not HAS_PLAYWRIGHT:
            raise ModuleNotFoundError("Instala playwright: pip install playwright && playwright install chromium")

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 Abriendo catálogo...")
        
        items_procesados = []
        encabezado_ubicacion = "Ingeniería - Biblioteca Central"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Ajustar la navegación para no bloquearse esperando 'networkidle'
            try:
                page.goto(self.target_url, wait_until="domcontentloaded", timeout=45000)
                
                # Esperar a que el contenedor principal del catálogo Primo VE aparezca
                page.wait_for_selector('prm-full-view, md-list, .holding-tile, body', timeout=20000)
                
                # Tiempo de gracia para que se ejecuten los scripts de Angular/Primo
                page.wait_for_timeout(4000)

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Advertencia durante la carga de página: {e}")

            # 1. Desplegar los acordeones para revelar ubicaciones ocultas
            try:
                botones_desplegar = page.query_selector_all('button[aria-expanded="false"], .md-accordion-toggle, [ng-click*="expand"]')
                for btn in botones_desplegar[:10]:
                    try:
                        btn.click(timeout=1000)
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
            except Exception as e:
                print(f"Aviso al desplegar filas: {e}")

            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')

        # 2. Extraer Encabezado General
        header_el = soup.find(text=re.compile(r'Biblioteca|Ingeniería|Ubicación', re.I))
        if header_el and header_el.parent:
            encabezado_ubicacion = header_el.parent.text.strip()

        # 3. Extraer filas de salas
        filas = soup.find_all(['md-list-item', 'div', 'tr', 'li'], class_=re.compile(r'item|holding|row|line|list-item', re.I))
        if not filas:
            filas = soup.find_all(['div', 'li'])

        vistas_unicas = set()

        for fila in filas:
            texto_completo = fila.text.strip()
            
            if any(k in texto_completo.lower() for k in ['sala', 'cubículo', 'estudio', 'préstamo', 'ejemplar']) and len(texto_completo) > 20:
                lineas = [l.strip() for l in fila.stripped_strings if len(l.strip()) > 0]
                
                nombre_sala = next((l for l in lineas if re.search(r'sala\s+(de\s+)?estudio\s+\d+', l, re.I)), None)
                if not nombre_sala:
                    nombre_sala = next((l for l in lineas if "sala" in l.lower() or "cubículo" in l.lower()), None)

                if not nombre_sala or nombre_sala in vistas_unicas:
                    continue
                vistas_unicas.add(nombre_sala)

                estado_raw = next((l for l in lineas if any(e in l.lower() for e in ['préstamo', 'prestamo', 'ejemplar', 'disponible'])), "Consultar")
                es_disponible = "ejemplar en biblioteca" in estado_raw.lower() or "disponible" in estado_raw.lower()

                # Extraer Hora Ocupada
                hora_ocupada = None
                match_hora = re.search(r'hasta\s+([\d\/\:\s]+(?:CLT|AM|PM)?)', estado_raw, re.I)
                if match_hora:
                    hora_ocupada = match_hora.group(1).strip()
                else:
                    match_hhmm = re.search(r'\b\d{2}:\d{2}(?::\d{2})?(?:\s*CLT)?\b', estado_raw)
                    if match_hhmm:
                        hora_ocupada = match_hhmm.group(0).strip()

                # Extraer Ubicación Desplegada
                ubicacion_desplegada = next(
                    (l for l in lineas if any(u in l.lower() for u in ['colección', 'coleccion', 'cf20', 'piso', 'sección', 'estantería']) and l != nombre_sala),
                    "Colección Cubículos de Estudio ; CF20 Salas FCFM"
                )

                items_procesados.append({
                    "sala": nombre_sala,
                    "disponible": es_disponible,
                    "estado_texto": estado_raw,
                    "ocupada_hasta": hora_ocupada,
                    "ubicacion_desplegada": ubicacion_desplegada
                })

        return {
            "encabezado": encabezado_ubicacion,
            "total_salas": len(items_procesados),
            "items": items_procesados
        }

    def run(self, output_filename="datos_magnolia.json"):
        try:
            datos = self.fetch_and_extract()
            payload = {
                "status": "success",
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "data": datos
            }
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Extracción exitosa: {datos['total_salas']} salas procesadas.")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Error: {e}")
            payload = {
                "status": "error",
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "message": str(e)
            }

        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return payload


if __name__ == "__main__":
    # URL del recurso en el catálogo Primo/Alma de la Universidad/Biblioteca
    URL_CATALOGO = "https://bibliotecadigital.uchile.cl/permalink/56UDC_INST/19vlqp5/alma991008208214803936"

    pipeline = BibliotecaMagnoliaPipeline(URL_CATALOGO)
    pipeline.run()