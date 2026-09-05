<?xml version="1.0" encoding="UTF-8"?>
<!--
  Icecast statistics as JSON, at /status-json.xsl

  This is the file Icecast looks for when something asks for
  /status-json.xsl, and it was simply missing from this web root, so every
  request got "404 Could not parse XSLT file". Nothing here is private: it is
  the same information the public status page shows, which is what the mounts
  are, what is playing on each and how many people are listening.

  One deliberate difference from the file Icecast ships. That one emits a bare
  object when there is exactly one mount and an array when there is more than
  one, so every client has to handle both shapes and most handle only the
  second. This always emits an array.
-->
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="1.0">
  <xsl:output method="text" omit-xml-declaration="yes"
              media-type="application/json" encoding="UTF-8"/>

  <!-- Fields Icecast reports as numbers. Everything else is quoted, so a
       station called "1984" stays a string rather than becoming a number. -->
  <xsl:variable name="numeric">
    <![CDATA[ listeners listener_peak listener_connections slow_listeners
    bitrate audio_bitrate audio_channels audio_samplerate samplerate channels
    quality public total_bytes_read total_bytes_sent outgoing_kbitrate
    incoming_bitrate connections client_connections clients sources
    stats source_client_connections source_relay_connections
    source_total_connections file_connections banned_IPs ]]>
  </xsl:variable>

  <xsl:template name="json-string">
    <xsl:param name="text"/>
    <xsl:choose>
      <!-- Backslash first, or the escapes added below would be escaped. -->
      <xsl:when test="contains($text, '\')">
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-before($text, '\')"/>
        </xsl:call-template>
        <xsl:text>\\</xsl:text>
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-after($text, '\')"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains($text, '&quot;')">
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-before($text, '&quot;')"/>
        </xsl:call-template>
        <xsl:text>\"</xsl:text>
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-after($text, '&quot;')"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains($text, '&#10;')">
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-before($text, '&#10;')"/>
        </xsl:call-template>
        <xsl:text>\n</xsl:text>
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-after($text, '&#10;')"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains($text, '&#13;')">
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-before($text, '&#13;')"/>
        </xsl:call-template>
        <xsl:text>\r</xsl:text>
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-after($text, '&#13;')"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:when test="contains($text, '&#9;')">
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-before($text, '&#9;')"/>
        </xsl:call-template>
        <xsl:text>\t</xsl:text>
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="substring-after($text, '&#9;')"/>
        </xsl:call-template>
      </xsl:when>
      <xsl:otherwise><xsl:value-of select="$text"/></xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <xsl:template name="field">
    <xsl:text>"</xsl:text>
    <xsl:call-template name="json-string">
      <xsl:with-param name="text" select="name()"/>
    </xsl:call-template>
    <xsl:text>":</xsl:text>
    <xsl:choose>
      <xsl:when test="contains($numeric, concat(' ', name(), ' '))
                      and string(number(.)) = normalize-space(.)">
        <xsl:value-of select="normalize-space(.)"/>
      </xsl:when>
      <xsl:otherwise>
        <xsl:text>"</xsl:text>
        <xsl:call-template name="json-string">
          <xsl:with-param name="text" select="."/>
        </xsl:call-template>
        <xsl:text>"</xsl:text>
      </xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <xsl:template match="/icestats">
    <xsl:text>{"icestats":{</xsl:text>
    <xsl:for-each select="*[not(self::source)]">
      <xsl:if test="position() &gt; 1"><xsl:text>,</xsl:text></xsl:if>
      <xsl:call-template name="field"/>
    </xsl:for-each>
    <xsl:if test="*[not(self::source)]"><xsl:text>,</xsl:text></xsl:if>
    <xsl:text>"source":[</xsl:text>
    <xsl:for-each select="source">
      <xsl:if test="position() &gt; 1"><xsl:text>,</xsl:text></xsl:if>
      <xsl:text>{"mount":"</xsl:text>
      <xsl:call-template name="json-string">
        <xsl:with-param name="text" select="@mount"/>
      </xsl:call-template>
      <xsl:text>"</xsl:text>
      <xsl:for-each select="*">
        <xsl:text>,</xsl:text>
        <xsl:call-template name="field"/>
      </xsl:for-each>
      <xsl:text>}</xsl:text>
    </xsl:for-each>
    <xsl:text>]}}</xsl:text>
  </xsl:template>
</xsl:stylesheet>
