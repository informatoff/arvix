import io
import json
import re
import html as html_lib

import discord


def _esc(text: str) -> str:
    return html_lib.escape(text) if text else ""


def _format_content(text: str) -> str:
    if not text:
        return ""
    t = _esc(text)

    def _code_block(m):
        lang = m.group(1) or ""
        code = m.group(2).strip()
        return f'<discord-code-block language="{lang}" code="{_esc(code)}"></discord-code-block>'

    t = re.sub(r'```(\w*)\n?(.*?)```', _code_block, t, flags=re.DOTALL)
    t = re.sub(r'`([^`]+)`', r'<discord-inline-code>\1</discord-inline-code>', t)
    t = re.sub(r'&lt;@!?(\d+)&gt;', r'<discord-mention type="user">\1</discord-mention>', t)
    t = re.sub(r'&lt;@&amp;(\d+)&gt;', r'<discord-mention type="role">\1</discord-mention>', t)
    t = re.sub(r'&lt;#(\d+)&gt;', r'<discord-mention type="channel">\1</discord-mention>', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', t)
    t = re.sub(r'__(.+?)__', r'<u>\1</u>', t)
    t = re.sub(r'~~(.+?)~~', r'<s>\1</s>', t)
    t = t.replace('\n', '<br/>')
    return t


def _format_embed(embed: discord.Embed) -> str:
    parts = ['<discord-embed']
    if embed.title:
        parts.append(f' embed-title="{_esc(embed.title)}"')
    if embed.author:
        parts.append(f' author-name="{_esc(embed.author.name or "")}"')
        if embed.author.icon_url:
            parts.append(f' author-image="{embed.author.icon_url}"')
    if embed.color and embed.color.value:
        parts.append(f' color="#{embed.color.value:06x}"')
    if embed.thumbnail and embed.thumbnail.url:
        parts.append(f' thumbnail="{embed.thumbnail.url}"')
    if embed.image and embed.image.url:
        parts.append(f' image="{embed.image.url}"')
    parts.append(' slot="embeds">')

    if embed.description:
        parts.append(f'<discord-embed-description slot="description">{_format_content(embed.description)}</discord-embed-description>')

    if embed.fields:
        parts.append('<discord-embed-fields slot="fields">')
        for f in embed.fields:
            inline = "true" if f.inline else "false"
            parts.append(
                f'<discord-embed-field field-title="{_esc(f.name)}" inline="{inline}">'
                f'{_format_content(f.value)}</discord-embed-field>'
            )
        parts.append('</discord-embed-fields>')

    if embed.footer and embed.footer.text:
        parts.append(
            f'<discord-embed-footer slot="footer">'
            f'{_esc(embed.footer.text)}</discord-embed-footer>'
        )

    parts.append('</discord-embed>')
    return ''.join(parts)


async def build_html_transcript(
    channel: discord.TextChannel,
    guild: discord.Guild,
    ticket_id: int,
    bot_name: str = "Arvix",
) -> io.BytesIO:
    messages: list[discord.Message] = []
    async for msg in channel.history(limit=None, oldest_first=True):
        messages.append(msg)

    profiles = {}
    for msg in messages:
        uid = str(msg.author.id)
        if uid not in profiles:
            role_color = ""
            if isinstance(msg.author, discord.Member) and msg.author.top_role and msg.author.top_role.color.value:
                role_color = f"#{msg.author.top_role.color.value:06x}"
            profiles[uid] = {
                "author": msg.author.display_name,
                "avatar": str(msg.author.display_avatar.url),
                "roleColor": role_color,
                "bot": msg.author.bot,
                "verified": False,
            }

    guild_icon = str(guild.icon.url) if guild.icon else ""
    ch_name = f"ticket-{ticket_id}"
    profiles_json = json.dumps(profiles, ensure_ascii=False)

    head = (
        f'<html><head>'
        f'<meta charSet="utf-8"/>'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        f'<link rel="icon" type="image/png" href="{guild_icon}"/>'
        f'<title>{ch_name}</title>'
        f'<script>document.addEventListener("click",t=>{{let e=t.target;if(!e)return;'
        f'let o=e?.getAttribute("data-goto");if(o){{let r=document.getElementById(`m-${{o}}`);'
        f'r?(r.scrollIntoView({{behavior:"smooth",block:"center"}}),'
        f'r.style.backgroundColor="rgba(148, 156, 247, 0.1)",'
        f'r.style.transition="background-color 0.5s ease",'
        f'setTimeout(()=>{{r.style.backgroundColor="transparent"}},1e3))'
        f':console.warn("Message not found.")}}}});</script>'
        f'<script>window.$discordMessage={{profiles:{profiles_json}}}</script>'
        f'<script type="module" src="https://cdn.jsdelivr.net/npm/@derockdev/discord-components-core@^3.6.1'
        f'/dist/derockdev-discord-components-core/derockdev-discord-components-core.esm.js"></script>'
        f'</head>'
    )

    body_parts = [
        '<body style="margin:0;min-height:100vh">',
        '<discord-messages style="min-height:100vh">',
        f'<discord-header guild="{_esc(guild.name)}" channel="{ch_name}" icon="{guild_icon}">',
        f'This is the start of #{ch_name} channel.',
        '</discord-header>',
    ]

    for msg in messages:
        ts = msg.created_at.isoformat()
        edited = "true" if msg.edited_at else "false"
        body_parts.append(
            f'<discord-message id="m-{msg.id}" timestamp="{ts}" '
            f'edited="{edited}" profile="{msg.author.id}">'
        )

        if msg.content:
            body_parts.append(_format_content(msg.content))

        for embed in msg.embeds:
            body_parts.append(_format_embed(embed))

        for att in msg.attachments:
            ct = att.content_type or ""
            if ct.startswith("image/"):
                body_parts.append(
                    f'<img src="{att.url}" alt="{_esc(att.filename)}" '
                    f'style="max-width:400px;border-radius:8px;margin:4px 0"/>'
                )
            else:
                body_parts.append(
                    f'<a href="{att.url}" style="color:#00aff4">'
                    f'{_esc(att.filename)}</a>'
                )

        body_parts.append('</discord-message>')

    body_parts.append(
        f'<div style="text-align:center;width:100%;padding:10px 0;color:#aaa;'
        f'font-family:sans-serif">{_esc(bot_name)} Ticket System. '
        f'Exported {len(messages)} messages </div>'
    )
    body_parts.append('</discord-messages></body></html>')

    html = head + '\n'.join(body_parts)
    return io.BytesIO(html.encode('utf-8'))
