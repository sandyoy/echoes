"""Convert markdown to docx with proper paragraph structure.
Handles headings, bold, lists, blockquotes, tables, code blocks properly."""
import re
import sys
import html

def md_to_docx(md_content):
    """Convert md text to a proper docx XML structure and return it as bytes."""
    lines = md_content.split('\n')
    
    docx_parts = []
    
    # Basic structure
    docx_parts.append('''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<?mso-application progid="Word.Document"?>
<w:wordDocument xmlns:w="http://schemas.microsoft.com/office/word/2003/wordml"
                xmlns:wx="http://schemas.microsoft.com/office/word/2003/auxHint"
                xmlns:o="urn:schemas-microsoft-com:office:office"
                xmlns:v="urn:schemas-microsoft-com:vml"
                xmlns:w10="urn:schemas-microsoft-com:office:word">
  <w:fonts>
    <w:defaultFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei" w:cs="Times New Roman"/>
    <w:font w:name="Microsoft YaHei"><w:altName w:value="微软雅黑"/></w:font>
    <w:font w:name="SimSun"><w:altName w:value="宋体"/></w:font>
  </w:fonts>
  <w:styles>
    <w:style w:type="paragraph" w:styleId="Normal">
      <w:name w:val="Normal"/>
      <w:rPr><w:sz w:val="24"/><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/></w:rPr>
    </w:style>
    <w:style w:type="paragraph" w:styleId="Heading1">
      <w:name w:val="heading 1"/>
      <w:rPr><w:b/><w:sz w:val="36"/><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/></w:rPr>
    </w:style>
    <w:style w:type="paragraph" w:styleId="Heading2">
      <w:name w:val="heading 2"/>
      <w:rPr><w:b/><w:sz w:val="30"/><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/></w:rPr>
    </w:style>
    <w:style w:type="paragraph" w:styleId="Heading3">
      <w:name w:val="heading 3"/>
      <w:rPr><w:b/><w:sz w:val="26"/><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/></w:rPr>
    </w:style>
    <w:style w:type="paragraph" w:styleId="Heading4">
      <w:name w:val="heading 4"/>
      <w:rPr><w:b/><w:sz w:val="24"/><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/></w:rPr>
    </w:style>
  </w:styles>
  <w:body>''')
    
    # Process line by line to handle content
    i = 0
    in_code_block = False
    code_lines = []
    in_table = False
    table_rows = []
    table_align = []
    
    # Smaller font for body, line spacing
    body_style = ' style="font-family:Microsoft YaHei;font-size:12pt;line-height:1.5;margin:4pt 0"'
    h1_style = ' style="font-family:Microsoft YaHei;font-size:20pt;font-weight:bold;margin:12pt 0 6pt 0;color:#1F4E79"'
    h2_style = ' style="font-family:Microsoft YaHei;font-size:16pt;font-weight:bold;margin:10pt 0 4pt 0;color:#2E75B6"'
    h3_style = ' style="font-family:Microsoft YaHei;font-size:14pt;font-weight:bold;margin:8pt 0 4pt 0;color:#2E75B6"'
    h4_style = ' style="font-family:Microsoft YaHei;font-size:12pt;font-weight:bold;margin:6pt 0 2pt 0"'
    li_style = ' style="font-family:Microsoft YaHei;font-size:12pt;line-height:1.5;margin:2pt 0 2pt 24pt"'
    blockquote_style = ' style="font-family:Microsoft YaHei;font-size:11pt;line-height:1.5;margin:6pt 0;padding:4pt 12pt;border-left:3pt solid #2E75B6;background-color:#F2F7FB"'
    
    def process_inline(text):
        """Process **bold** and other inline formatting"""
        # Process bold first
        parts = []
        last_end = 0
        for m in re.finditer(r'\*\*(.+?)\*\*', text):
            if m.start() > last_end:
                parts.append(html.escape(text[last_end:m.start()]))
            parts.append(f'<b>{html.escape(m.group(1))}</b>')
            last_end = m.end()
        if last_end < len(text):
            parts.append(html.escape(text[last_end:]))
        result = ''.join(parts) if parts else html.escape(text)
        # Process simple markers
        result = result.replace('✅ ', '<span style="color:#27AE60">✅</span> ')
        result = result.replace('⚠️ ', '<span style="color:#E74C3C">⚠️</span> ')
        return result
    
    def make_p(text, style_attr, extra_class=""):
        """Make a paragraph XML"""
        content = process_inline(text)
        if content.strip():
            return f'<w:p><w:r><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/><w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">{content}</w:t></w:r></w:p>'
        return '<w:p><w:r><w:t xml:space="preserve"> </w:t></w:r></w:p>'
    
    def make_heading(text, level):
        content = process_inline(text)
        style_id = f"Heading{level}"
        return f'<w:p><w:pPr><w:pStyle w:val="{style_id}"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/><w:b/><w:sz w:val="{36-(level-1)*6}"/></w:rPr><w:t>{content}</w:t></w:r></w:p>'
    
    def make_list_item(text, indent=1):
        content = process_inline(text)
        return f'<w:p><w:pPr><w:ind w:left="{indent*360}" w:hanging="180"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/><w:sz w:val="24"/></w:rPr><w:t xml:space="preserve">• {content}</w:t></w:r></w:p>'
    
    def make_blockquote(text):
        content = process_inline(text)
        return f'<w:p><w:pPr><w:ind w:left="360" w:right="180"/><w:shd w:val="clear" w:color="auto" w:fill="F2F7FB"/><w:pBdr><w:left w:val="single" w:sz="12" w:space="8" w:color="2E75B6"/></w:pBdr></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/><w:i/><w:sz w:val="22"/><w:color w:val="555555"/></w:rPr><w:t>{content}</w:t></w:r></w:p>'
    
    def make_table(headers, rows, aligns):
        """Create a simple XML table"""
        xml = '<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/></w:tblBorders></w:tblPr>'
        
        # Header row
        xml += '<w:tr><w:trPr><w:trHeight w:val="360"/></w:trPr>'
        for i, h in enumerate(headers):
            xml += f'<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="2E75B6"/></w:tcPr><w:p><w:r><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/><w:b/><w:color w:val="FFFFFF"/><w:sz w:val="22"/></w:rPr><w:t>{html.escape(h.strip())}</w:t></w:r></w:p></w:tc>'
        xml += '</w:tr>'
        
        # Data rows
        for row in rows:
            xml += '<w:tr>'
            for j, cell in enumerate(row):
                content = process_inline(cell.strip())
                align = aligns[j] if j < len(aligns) else 'left'
                xml += f'<w:tc><w:p><w:r><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:h-ansi="Microsoft YaHei"/><w:sz w:val="20"/></w:rPr><w:t xml:space="preserve">{content}</w:t></w:r></w:p></w:tc>'
            xml += '</w:tr>'
        
        xml += '</w:tbl><w:p><w:r><w:t> </w:t></w:r></w:p>'
        return xml
    
    def make_code_block(lines):
        """Format code block as monospace with background"""
        code_text = '<br/>'.join(html.escape(l) for l in lines if l.strip())
        return f'<w:p><w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F5F5F5"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Consolas" w:h-ansi="Consolas"/><w:sz w:val="18"/><w:color w:val="333333"/></w:rPr><w:t xml:space="preserve">{code_text}</w:t></w:r></w:p>'
    
    def make_horizontal_rule():
        return '<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="CCCCCC"/></w:pBdr></w:pPr></w:p>'
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Handle code blocks
        if line.startswith('```'):
            if in_code_block:
                docx_parts.append(make_code_block(code_lines))
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
                code_lines = []
            i += 1
            continue
        
        if in_code_block:
            code_lines.append(line)
            i += 1
            continue
        
        # Skip empty lines in sequence
        if not line:
            i += 1
            continue
        
        # Heading 1
        if line.startswith('# ') and not line.startswith('## '):
            docx_parts.append(make_heading(line[2:], 1))
            i += 1
            continue
        
        # Heading 2
        if line.startswith('## ') and not line.startswith('### '):
            docx_parts.append(make_heading(line[3:], 2))
            i += 1
            continue
        
        # Heading 3
        if line.startswith('### ') and not line.startswith('#### '):
            docx_parts.append(make_heading(line[4:], 3))
            i += 1
            continue
        
        # Heading 4
        if line.startswith('#### '):
            docx_parts.append(make_heading(line[5:], 4))
            i += 1
            continue
        
        # Horizontal rule
        if line.startswith('---') or line.startswith('***'):
            docx_parts.append(make_horizontal_rule())
            i += 1
            continue
        
        # Blockquote
        if line.startswith('> '):
            content = line[2:]
            # Collect consecutive blockquote lines
            while i + 1 < len(lines) and lines[i + 1].strip().startswith('> '):
                i += 1
                content += ' ' + lines[i].strip()[2:]
            docx_parts.append(make_blockquote(content))
            i += 1
            continue
        
        # Table (simple pipe tables)
        if '|' in line and line.startswith('|'):
            # Check if next line is separator
            if i + 1 < len(lines) and '---' in lines[i + 1]:
                headers = [h.strip() for h in line.split('|') if h.strip()]
                i += 2
                # Parse alignments from separator
                sep = lines[i - 1].strip()
                align_parts = sep.split('|')[1:-1]
                aligns = []
                for a in align_parts:
                    a = a.strip()
                    if a.startswith(':') and a.endswith(':'):
                        aligns.append('center')
                    elif a.startswith(':'):
                        aligns.append('left')
                    elif a.endswith(':'):
                        aligns.append('right')
                    else:
                        aligns.append('left')
                
                # Read data rows
                rows = []
                while i < len(lines) and '|' in lines[i] and not lines[i].strip().startswith('|'):
                    i += 1  # Skip empty
                while i < len(lines) and '|' in lines[i]:
                    row_cells = [c.strip() for c in lines[i].split('|') if c.strip()]
                    if row_cells:
                        rows.append(row_cells)
                    i += 1
                
                docx_parts.append(make_table(headers, rows, aligns))
                continue
            else:
                # Single row table
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if cells:
                    docx_parts.append(f'<w:p><w:r><w:t>{html.escape(" | ".join(cells))}</w:t></w:r></w:p>')
                i += 1
                continue
        
        # List items
        if line.startswith('- ') or line.startswith('* '):
            content = line[2:] if line.startswith('- ') else line[2:]
            # Collect continuation lines (indented)
            while i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].strip().startswith('- ') and not lines[i + 1].strip().startswith('* ') and not lines[i + 1].strip().startswith('#'):
                if lines[i + 1].strip().startswith('> ') or lines[i + 1].strip().startswith('|') or lines[i + 1].strip().startswith('```'):
                    break
                if lines[i + 1].strip():
                    content += ' ' + lines[i + 1].strip()
                i += 1
            docx_parts.append(make_list_item(content))
            i += 1
            continue
        
        # Everything else is a paragraph
        # Collect consecutive text lines into one paragraph
        para_text = line
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if not next_line or next_line.startswith('#') or next_line.startswith('- ') or next_line.startswith('* ') or next_line.startswith('|') or next_line.startswith('> ') or next_line.startswith('```') or next_line.startswith('---'):
                break
            para_text += ' ' + next_line
            i += 1
        
        docx_parts.append(make_p(para_text, body_style))
        i += 1
    
    docx_parts.append('</w:body></w:document>')
    return '\n'.join(docx_parts)


if __name__ == '__main__':
    import os
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    
    with open(input_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    xml_content = md_to_docx(md_content)
    
    # Write as Word ML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(xml_content)
    
    file_size = os.path.getsize(output_path)
    print(f"Done. Generated {output_path} ({file_size} bytes)")
