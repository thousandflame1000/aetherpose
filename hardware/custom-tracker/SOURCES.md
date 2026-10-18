# Source references

Consulted 2026-10-18. Manufacturer PDFs are local reference downloads, not authored by this project. They are excluded from Git and the review ZIP. Do not redistribute manufacturer documents beyond their license terms.

| Local reference | Original source |
|---|---|
| `sources/esp32.pdf` | https://www.espressif.com/sites/default/files/documentation/esp32-c3-mini-1_datasheet_en.pdf |
| `sources/bmi270.pdf` | https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf |
| `sources/qmc5883p.pdf` | https://www.qstcorp.com/upload/pdf/202512/2C939E5AA0704285BC3BE71132B8629B.pdf |
| `sources/bq24075.pdf` | https://www.ti.com/lit/ds/symlink/bq24075.pdf |
| `sources/tlv755.pdf` | https://www.ti.com/lit/ds/symlink/tlv755p.pdf |

The ESP32 footprint is supplied by [Espressif's official KiCad libraries](https://github.com/espressif/kicad-libraries). Other packaged footprints are from [KiCad's footprint repository](https://github.com/KiCad/kicad-footprints), a historical upstream snapshot. Footprint hashes/URLs appear in `sources/upstream-manifest.json`; using a stock footprint does not replace package-specific review. Embedded PCB footprints have references, positions and net assignments added by `build_design.py`.

Routing used [FreeRouting 1.9.0](https://github.com/freerouting/freerouting/releases/tag/v1.9.0), single-threaded operation, with post-route optimization disabled for the delivered draft. FreeRouting is an external tool and is not included in the review ZIP. The generated DSN/SES files are included to make routing inspectable. Geometry checks use [Shapely](https://shapely.readthedocs.io/); engineering previews use PyMuPDF to convert generated SVGs. A successful routing run is not hardware validation.
