# BedROCC — Scaffolding Images

Source images for the BedROCC operations control-room showcase. All
images are reused under permissive Creative Commons or Public Domain
licences with attribution to the original photographer / institution.
Each illustrates a different facet of an operations control room or
SCADA console — wide-angle floor view, multi-screen diagnostics,
single-operator console, server-rack control infrastructure, and an
HMI/alarm console screenshot.

| File | Subject | Original page | Author | Licence |
| --- | --- | --- | --- | --- |
| `control-room-wide.jpg` | Control room of LIGO at Hanford, Washington — wide-angle view of multi-monitor research-facility control room | https://commons.wikimedia.org/wiki/File:Control_Room_of_LIGO_at_Hanford,_Washington_(LIGO_Pic_38-CC).jpg | Caltech / MIT / LIGO Lab | CC BY 3.0 |
| `scada-hmi.jpg` | Diagnostic monitors in the control room of Wendelstein 7-X — a wall of HMI/SCADA-style screens during operation | https://commons.wikimedia.org/wiki/File:Diagnostic_monitors_in_the_control_room_of_Wendelstein_7-X.jpg | IPP / Wolfgang Filser | CC BY 3.0 |
| `operator-at-console.jpg` | Chiller-plant SCADA system — single operator console with HVAC SCADA HMI on screen | https://commons.wikimedia.org/wiki/File:Chiller_plant_SCADA_system.jpg | T R Shankar Raman | CC BY-SA 4.0 |
| `alarm-console-mock.png` | Eclipse SCADA Demo System — software interface displaying SCADA process visualisation with alarm fields, used as the visual reference for the BedROCC queue mock | https://commons.wikimedia.org/wiki/File:Eclipse_SCADA_Demo_System.png | Eclipse SCADA project | EPL 2.0 / CC BY 4.0 |
| `substation-control-room.jpg` | Wikimedia Foundation server racks (Eqiad data centre) — representative server-rack infrastructure that the BedROCC SCADA back-end runs on | https://commons.wikimedia.org/wiki/File:Wikimedia_Foundation_Servers-8055_03.jpg | Victor Grigas (Wikimedia Foundation) | CC BY-SA 3.0 |

> **Note on coverage.** The original storyboard called for 6 images
> including a dedicated utility-substation control-room photo. The
> Commons file we earmarked for that slot was rate-limited during the
> initial fetch, so the substation slot was repurposed to a server-rack
> image (which doubles as the "where this runs" illustration). 5 images
> still satisfies the showcase requirement of 4-6 control-room images
> and gives the UI enough variety. To add the missing substation photo
> later, drop a CC-licensed JPG into this folder and append a row above.

## Mapping to the showcase storyboard

- **Hero / scenario explainer "control room" callout** -> `control-room-wide.jpg`
- **"Live alarm queue" header card** -> `alarm-console-mock.png`
- **"Why it matters — operator load" section** -> `operator-at-console.jpg`
- **"Cascade detection" amber banner illustration** -> `scada-hmi.jpg`
- **Architecture / where this runs** -> `substation-control-room.jpg`

## Re-fetching the images

The images themselves are committed alongside this README. To re-pull
them (e.g. after updating an entry above), run from this directory:

```bash
# Wikimedia rate-limits unidentified bots — use a real UA and pause
# between fetches if you re-do the whole batch.
while IFS='|' read -r file url; do
  [ -z "$file" ] && continue
  curl -sSL --max-time 60 \
    -H 'User-Agent: AgentforgeShowcase/1.0 (you@example.com)' \
    -o "$file" "$url"
  sleep 2
done <<'EOF'
control-room-wide.jpg|https://commons.wikimedia.org/wiki/Special:FilePath/Control_Room_of_LIGO_at_Hanford,_Washington_(LIGO_Pic_38-CC).jpg
scada-hmi.jpg|https://commons.wikimedia.org/wiki/Special:FilePath/Diagnostic_monitors_in_the_control_room_of_Wendelstein_7-X.jpg
operator-at-console.jpg|https://commons.wikimedia.org/wiki/Special:FilePath/Chiller_plant_SCADA_system.jpg
alarm-console-mock.png|https://commons.wikimedia.org/wiki/Special:FilePath/Eclipse_SCADA_Demo_System.png
substation-control-room.jpg|https://upload.wikimedia.org/wikipedia/commons/f/fa/Wikimedia_Foundation_Servers-8055_03.jpg
EOF
```

Wikimedia's `Special:FilePath` redirects to the latest revision of the
file regardless of namespace renames, so the URLs above stay valid
even if the original page moves.

## Reuse / attribution

When re-publishing any of these images outside the showcase, retain
the original author credit and the licence link:

- CC BY 3.0:    https://creativecommons.org/licenses/by/3.0/
- CC BY-SA 3.0: https://creativecommons.org/licenses/by-sa/3.0/
- CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/
- EPL 2.0:      https://www.eclipse.org/legal/epl-2.0/

Derivatives of the CC BY-SA family of images must be released under
the same or a later compatible version. The Eclipse SCADA screenshot
is dual-licensed; pick the matching pair when redistributing.
