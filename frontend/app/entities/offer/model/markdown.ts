import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false }).disable('image')

export const renderOfferMarkdown = (source: string): string => markdown.render(source)
