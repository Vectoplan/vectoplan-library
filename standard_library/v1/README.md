# VECTOPLAN Standard Library V1

Dieser Ordner ist die kanonische, beim Service-Start geladene VPLIB-Quelle.

- `packages/` enthält 48 VPLIB-Familien mit 332 Varianten für Hochbau, Tiefbau und Ingenieurbau.
- `catalog.json` ist der deterministische Index des erzeugten Stands.
- Jede Familie enthält `render/cad_patterns.json` mit den tatsächlich verwendeten Vektor-Schraffuren.
- `scripts/build_standard_library_v1.py` erzeugt und validiert den kompletten Stand über denselben Generator wie die VPLIB-Oberfläche.

Neuaufbau und reine Prüfung:

```shell
python scripts/build_standard_library_v1.py
python scripts/build_standard_library_v1.py --check
```

Der Generator überschreibt nur Familien mit derselben stabilen Taxonomie/Slug-Kombination. Neue Familien und Varianten werden im Builder ergänzt; vorhandene UUIDs bleiben dabei stabil.
