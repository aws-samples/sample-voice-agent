#!/usr/bin/env python3
"""
Convert text and markdown files to PDF for Bedrock Knowledge Base ingestion.

Usage:
    python convert_to_pdf.py [--force]

Options:
    --force    Re-convert even if PDF already exists

Bedrock Knowledge Bases work more reliably with PDF files for document chunking
and retrieval. This script converts .txt and .md files to PDF format.
"""

import argparse
import sys
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import inch
except ImportError:
    print("Error: reportlab is required. Install with: pip install reportlab")
    sys.exit(1)


def convert_text_to_pdf(input_path: Path, output_path: Path) -> bool:
    """Convert a text file to PDF.

    Args:
        input_path: Path to the input .txt or .md file
        output_path: Path for the output .pdf file

    Returns:
        True if conversion succeeded, False otherwise
    """
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )

        styles = getSampleStyleSheet()
        title_style = styles['Heading1']
        heading_style = styles['Heading2']
        question_style = ParagraphStyle(
            'Question',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
        )
        answer_style = styles['Normal']

        story = []
        lines = content.split('\n')

        # First non-empty line as title
        for i, line in enumerate(lines):
            if line.strip():
                story.append(Paragraph(line.strip(), title_style))
                story.append(Spacer(1, 0.25 * inch))
                lines = lines[i + 1:]
                break

        for line in lines:
            line_stripped = line.strip()

            if not line_stripped:
                story.append(Spacer(1, 0.1 * inch))
            elif line_stripped.isupper() and len(line_stripped) < 40:
                # Section headers (all caps, short)
                story.append(Spacer(1, 0.2 * inch))
                story.append(Paragraph(line_stripped, heading_style))
            elif line_stripped.startswith('Q:') or line_stripped.startswith('**Q:'):
                # Questions
                clean_line = line_stripped.replace('**', '')
                story.append(Paragraph(clean_line, question_style))
            elif line_stripped.startswith('A:') or line_stripped.startswith('**A:'):
                # Answers
                clean_line = line_stripped.replace('**', '')
                story.append(Paragraph(clean_line, answer_style))
                story.append(Spacer(1, 0.1 * inch))
            elif line_stripped.startswith('#'):
                # Markdown headers
                level = len(line_stripped) - len(line_stripped.lstrip('#'))
                header_text = line_stripped.lstrip('#').strip()
                if level == 1:
                    story.append(Paragraph(header_text, title_style))
                else:
                    story.append(Paragraph(header_text, heading_style))
            elif line_stripped.startswith('-') or line_stripped.startswith('*'):
                # List items
                bullet_text = '• ' + line_stripped.lstrip('-*').strip()
                story.append(Paragraph(bullet_text, answer_style))
            else:
                # Regular paragraphs
                story.append(Paragraph(line_stripped, answer_style))

        doc.build(story)
        return True

    except Exception as e:
        print(f"  Error converting {input_path.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Convert text/markdown files to PDF for Bedrock Knowledge Base'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Re-convert even if PDF already exists',
    )
    args = parser.parse_args()

    # Get the directory containing this script
    script_dir = Path(__file__).parent

    # Find all txt and md files
    text_files = list(script_dir.glob('*.txt')) + list(script_dir.glob('*.md'))

    if not text_files:
        print("No .txt or .md files found to convert.")
        return 0

    converted = 0
    skipped = 0
    failed = 0

    for input_path in text_files:
        output_path = input_path.with_suffix('.pdf')

        # Skip if PDF already exists (unless --force)
        if output_path.exists() and not args.force:
            print(f"  Skipping {input_path.name} (PDF exists, use --force to overwrite)")
            skipped += 1
            continue

        print(f"  Converting {input_path.name} -> {output_path.name}")

        if convert_text_to_pdf(input_path, output_path):
            converted += 1
            # Optionally remove the source file after successful conversion
            # input_path.unlink()
        else:
            failed += 1

    print(f"\nSummary: {converted} converted, {skipped} skipped, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
