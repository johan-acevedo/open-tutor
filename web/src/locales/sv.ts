// Swedish catalogue: the only place user-visible Swedish lives in web/src.
// Every other .ts/.tsx file looks strings up by key, so adding a second
// language later means adding one more file with the same keys.
// Missing keys are a compile error (SvKey), and the guard test fails on any
// Swedish-looking literal outside locales/ and *.test.* files.

export const localeId = 'sv' as const;
export const htmlLang = 'sv' as const;

export const sv = {
  // App shell
  'app.connecting': 'Ansluter till tutorn…',
  'app.micBlockedText': 'Jag hör dig inte just nu. Du kan skriva här under.',
  'app.retry': 'Försök igen',
  'app.resumeContinue': 'Fortsätt samtalet',
  'app.resumeListen': 'Tryck för att höra mig',
  'app.reconnecting': 'Tappade kontakten – försöker igen…',
  'app.disconnected': 'Tappade kontakten.',
  'app.restart': 'Starta igen',
  'app.ending': 'Avslutar samtalet…',
  'app.endButton': 'Avsluta',
  'app.endButtonAria': 'Avsluta sessionen',
  'app.cameraInputAria': 'Fota läxan',
  'app.youPrefix': 'Du:',

  // Avatar / status pill
  'avatar.tutorLabel': 'Tutorn',
  'pill.speaking': 'Pratar',
  'pill.waiting': 'Jag väntar',
  'pill.watching': 'Väntar medan du tittar',
  'pill.drawing': 'Ritar…',
  'pill.thinking': 'Tänker…',
  'pill.textWaiting': 'Väntar på text',
  'pill.listening': 'Lyssnar',
  'pill.hello': 'Hej!',

  // Board
  'board.navLabel': 'Bläddra i tavlan',
  'board.back': '← Tillbaka',
  'board.forward': 'Framåt →',
  'board.emptyGreeting': 'Hej{name}!',
  'board.emptyBody': 'Här hamnar det vi jobbar med.',
  'board.emptyHint': 'Säg hej — tutorn ritar upp här.',

  // Bottom bar
  'bottombar.controlsLabel': 'Samtalskontroller',
  'bottombar.attachAria': 'Lägg till läxa — välj fil',
  'bottombar.attachTitle': 'Lägg till läxa',
  'bottombar.inputPlaceholder': 'Skriv här om du vill…',
  'bottombar.inputAria': 'Skriv här om du vill',
  'bottombar.send': 'Skicka',
  'bottombar.micBlocked': 'Mikrofon blockerad',
  'bottombar.micOff': 'Stäng av mikrofonen',
  'bottombar.micOn': 'Mikrofon av — sätt på mikrofonen',
  'bottombar.micOnTitle': 'Mikrofon på',
  'bottombar.micOffTitle': 'Mikrofon av',

  // Top menu (in-call)
  'topmenu.menuLabel': 'Meny',
  'topmenu.inboxLabel': 'Inkorg för läxor',
  'topmenu.inboxEmpty': 'Ingen läxa skickad än',
  'topmenu.inboxOne': '{count} läxa skickad',
  'topmenu.inboxMany': '{count} läxor skickade',
  'topmenu.dropHint': 'Du kan också dra in en bild eller pdf i fönstret.',
  'topmenu.photo': 'Fota läxan',
  'topmenu.chooseImage': 'Välj bild',
  'topmenu.switchFallback': 'Byt elev',
  'topmenu.switchHint': 'Avslutar samtalet',
  'topmenu.aboutTitle': 'Om Talarum',
  'topmenu.aboutBy': 'Gjord av Johan Acevedo.',
  'topmenu.privacyLink': 'Läs om integritet',

  // Start menu (pre-call)
  'startmenu.about': 'Om Talarum',
  'startmenu.aboutText': 'Talarum är ett experiment: en AI du pratar med om läxan. Den förklarar och ritar på tavlan medan du själv löser uppgiften. Gratis än så länge.',
  'startmenu.privacy': 'Integritet',
  'startmenu.privacyText': 'Din profil och anteckningar sparas bara i den här webbläsaren. Röstsamtalet går via våra leverantörer så att tutorn kan höra dig. Inget konto behövs.',
  'startmenu.privacyLink': 'Läs om integritet',

  // Homework tray
  'tray.label': 'Lägg till läxa',
  'tray.pickerTitle': 'Visa mig din läxa',
  'tray.readyTitle': 'Redo att skicka?',
  'tray.previewAlt': 'Förhandsvisning av läxan',
  'tray.photo': 'Fota läxan',
  'tray.retake': 'Ta om foto',
  'tray.choose': 'Välj bild eller PDF',
  'tray.cancel': 'Avbryt',
  'tray.sending': 'Skickar…',
  'tray.send': 'Skicka till tutorn',
  'tray.hint': 'Kontrollera att texten går att läsa innan du skickar.',
  'tray.remove': 'Ta bort',
  'tray.removeAria': 'Ta bort {name}',
  'tray.fallbackName': 'Foto',
  'tray.fallbackImageTitle': 'Bild',
  'tray.fallbackImageSource': 'bild',
  'tray.fallbackPdfTitle': 'PDF',
  'tray.fallbackPdfSource': 'pdf',
  'tray.pastedTitle': 'Inklistrad text',

  // End card
  'end.greetingNamed': 'Bra jobbat idag, {name}!',
  'end.greetingAnon': 'Bra jobbat idag!',
  'end.idle': 'Samtalet avslutades eftersom det var tyst en stund.',
  'end.topicLabel': 'Det här pratade vi om:',
  'end.clickedLabel': 'Det här klickade:',
  'end.nextLabel': 'Nästa gång:',
  'end.back': 'Tillbaka till start',
  'end.shareTitleYoung': 'Tipsa andra föräldrar',
  'end.shareTitleOld': 'Tipsa någon',
  'end.shareText': 'Känner du någon som också kämpar med läxan? Talarum är gratis än så länge.',
  'end.shareButton': 'Tipsa',
  'end.shareCopied': 'Kopierat ✓',

  // Household picker (siblings on one device)
  'picker.title': 'Vem ska prata?',
  'picker.new': '+ Någon ny',
  'picker.newHint': 'Börja utan sparad profil',
  'picker.back': 'Tillbaka',
  'picker.withCompanion': '{name} · {companion}',

  // Cards (resources, homework, pending)
  'cards.drawing': 'Ritar…',
  'cards.sourcePrefix': 'Källa:',
  'cards.openNewTab': 'Öppna i ny flik',
  'cards.thinkAboutPrefix': 'Fundera på:',
  'cards.submittedAlt': 'Inlämnad bild {n}',
  'cards.doneTalk': 'Klar – prata vidare',

  // Phone fox strip / hero
  'fox.showPage': 'Visa sidan',
  'fox.showPageWithTitle': 'Visa sidan: {title}',
  'fox.showCompanion': 'Visa {name}',

  // Welcome (voice-first start)
  'welcome.starting': 'Startar…',

  // Band copy (per-band companion and start page)
  'band.primary.companionName': 'Räven',
  'band.primary.welcomeBubble': 'Hej!',
  'band.primary.returningBubble': 'Hej {name}!',
  'band.primary.notYou': 'Inte {name}?',
  'band.primary.startButton': 'Prata med Räven',
  'band.primary.switchStudent': 'Byt elev',
  'band.middle.companionName': 'Lodjuret',
  'band.middle.welcomeBubble': 'Hej!',
  'band.middle.returningBubble': 'Hej {name}!',
  'band.middle.notYou': 'Inte {name}?',
  'band.middle.startButton': 'Prata med Lodjuret',
  'band.middle.switchStudent': 'Byt elev',
  'band.upper.companionName': 'Björnen',
  'band.upper.welcomeBubble': 'Hej!',
  'band.upper.returningBubble': 'Hej {name}!',
  'band.upper.notYou': 'Inte {name}?',
  'band.upper.startButton': 'Prata med Björnen',
  'band.upper.switchStudent': 'Byt person',

  // Landing page (start view: hero, steps, footer)
  'landing.navLabel': 'Navigering',
  'landing.titlePrefix': 'Läxhjälp du kan ',
  'landing.titleAccent': 'prata',
  'landing.titleSuffix': ' med',
  'landing.titlePeriod': '.',
  'landing.howTitle': 'Så funkar det',
  'landing.step1Title': 'Visa läxan',
  'landing.step1Text': 'Fota uppgiften, så ser {companion} den också.',
  'landing.step2Title': 'Prata med {companion}',
  'landing.step2Text': 'Säg vad du tänker. {companion} lyssnar och frågar.',
  'landing.step3Title': 'Lös den ihop',
  'landing.step3Text': 'Steg för steg på tavlan, i din takt.',
  'landing.footerText': 'Talarum är ett experiment. Du behöver inget konto, och det du gör sparas bara i din webbläsare.',
  'landing.footerPrivacy': 'Läs om integritet',
  'landing.unifiedIntro': 'Talarum är en AI du pratar med om läxan. Den lyssnar, förklarar och ritar medan du själv löser uppgiften. Gratis än så länge.',
  'landing.chooserTitle': 'Välj vem du vill prata med',
  'landing.introPrimary': 'Räven är en AI för dig som går i åk 1–6. Räven lyssnar, förklarar och ritar på tavlan medan du själv löser uppgiften. Gratis än så länge.',
  'landing.bandsTitlePrimary': 'Går du i en annan årskurs?',
  'landing.audiencePrimary': 'Åk 1–6',
  'landing.introMiddle': 'Lodjuret är en AI för dig som går på högstadiet. Lodjuret lyssnar, förklarar och ritar på tavlan medan du själv löser uppgiften. Gratis än så länge.',
  'landing.bandsTitleMiddle': 'Går du i en annan årskurs?',
  'landing.audienceMiddle': 'Högstadiet',
  'landing.introUpper': 'Björnen är en AI för dig som går på gymnasiet eller pluggar som vuxen. Björnen lyssnar, förklarar och ritar på tavlan medan du själv löser uppgiften. Gratis än så länge.',
  'landing.bandsTitleUpper': 'Någon yngre hemma?',
  'landing.audienceUpper': 'Gymnasiet och vuxna',
  'landing.paperPrimary': '36 + 47 = ?',
  'landing.paperMiddle': '3x + 5 = 20',
  'landing.paperUpper': 'f(x) = x² + 3x',
  'landing.row1Primary': '30 + 40 = 70',
  'landing.row2Primary': '6 + 7 = 13',
  'landing.row3Primary': '70 + 13 = 83',
  'landing.row1Middle': '3x + 5 = 20',
  'landing.row2Middle': '3x = 15',
  'landing.row3Middle': 'x = 5',
  'landing.row1Upper': 'f(x) = x² + 3x',
  'landing.row2Upper': 'f′(x) = 2x + 3',
  'landing.row3Upper': 'f′(2) = 7',
  'landing.listenAria': '{greeting} Lyssna på {companion}',
  'landing.withCompanion': 'med {companion}',

  // Toasts (session errors)
  'toast.full': 'Det är fullt just nu. Försök igen om en stund.',
  'toast.startFailed': 'Kunde inte starta sessionen. Kontrollera anslutningen och försök igen.',
  'toast.connectFailed': 'Kunde inte ansluta till samtalet. Försök igen.',
  'toast.sendFailed': 'Kunde inte skicka meddelandet. Försök igen.',
  'toast.notifyFailed': 'Kunde inte meddela tutorn. Försök igen.',
  'toast.imageFailed': 'Bilden kunde inte läsas eller skickas. Prova JPG, PNG eller PDF och kontrollera anslutningen.',
  'toast.pdfFailed': 'Kunde inte läsa PDF:en. Prova en annan fil.',
  'toast.pdfEmpty': 'PDF:en verkar vara tom.',
  'toast.textFailed': 'Kunde inte skicka texten. Försök igen.',
  'toast.fileType': 'Den filtypen stöds inte ännu. Prova PDF, PNG eller JPG.',
  'toast.allFailed': 'Alla filer kunde inte skickas. Prova JPG, PNG eller PDF.',

  // Smart Screen shell (injected into the frame; shell.js has no Swedish of its own)
  'shell.send': 'Skicka',
  'shell.sent': 'Skickat ✓',
  'shell.answerLabel': 'Ditt svar',
  'shell.gapLabel': 'Lucka',
  'shell.loading': 'Laddar {topic} …',
  'shell.bc': 'f.Kr.',
  'shell.ad': 'e.Kr.',
  'shell.mapCreditHistorical': 'Gränser: historical-basemaps · Natural Earth',
  'shell.mapCredit': 'Natural Earth',

  // Dev demo (screen-demo=1) and design review: example lesson content
  'demo.klockanTitle': 'Vad är klockan?',
  'demo.divisionTitle': 'Pris per kilo',
  'demo.longLine': 'Titta på klockan på sidan. Den stora visaren pekar på tolv, och den lilla står på tre. Då är klockan tre, eller hur? Säg vad du tror att den lilla visaren betyder.',
  'demo.greeting': 'Hej! Jag heter {companion}. Vad jobbar du med idag?',
  'demo.answersLabel': 'Svar från barnet',
  'demo.showPatch': 'Visa patch',
  'demo.reveal': 'Avslöja',
  'demo.point': 'Peka',
  'demo.header': 'Skärm-demo',
  // Brand
  'brand.name': 'Talarum',

  // Privacy page (/integritet)
  'privacy.title': 'Om Talarum och din integritet',
  'privacy.intro': 'Talarum är läxhjälp som du kan prata med på svenska. Den förklarar och visar exempel på skärmen medan du själv löser uppgiften. Johan Acevedo har skapat Talarum som ett experiment. Det är gratis än så länge och du behöver inget konto.',
  'privacy.browserTitle': 'Det webbläsaren kommer ihåg',
  'privacy.browserBody': 'Webbläsaren sparar förnamn, årskurs och korta anteckningar från tidigare samtal. Den sparar också ett slumpmässigt nummer som gör att besök från samma webbläsare kan kännas igen. Vill du ta bort allt som sparats? Rensa webbplatsdata för Talarum i webbläsaren. När ett nytt samtal börjar skickas profiluppgifter och tidigare anteckningar med så att läxhjälpen kan fortsätta där ni slutade.',
  'privacy.sendTitle': 'Det som skickas när ni pratar',
  'privacy.sendBody': 'LiveKit förmedlar samtalet. Soniox gör talet till text och Deepgram läser upp svaret. För att svara och visa förklaringar skickas samtalstext, det som skrivs och läxmaterial som delas till språkmodeller som tar fram svaren. Sökord kan skickas till Exa för länkar och till Wikimedia Commons eller Parallel för bilder. Cloudflare levererar webbplatsen.',
  'privacy.training': 'En av språkmodellerna, Muse Spark Contributor från Meta, får använda samtalstext och svar för att förbättra framtida modeller.',
  'privacy.stats': 'Talarum visar ingen reklam. Vi använder PostHog i EU för att se hur ofta samtal startar, hur länge de pågår och om något går fel. Vi skickar inga namn dit och använder inte statistiken för reklam eller för att bedöma enskilda barn.',
  'privacy.togetherTitle': 'Börja gärna tillsammans',
  'privacy.togetherBody': 'Sitt gärna med första gången, särskilt med yngre barn. Använd bara förnamn. Skriv eller säg aldrig efternamn, personnummer, adress eller uppgifter om hälsa. Titta på läxblad och foton tillsammans och täck över namn och andra personliga uppgifter innan ni delar dem.',
  'privacy.contactPrefix': 'Frågor? Skriv till',
  'privacy.contactEmail': 'hej@talarum.se',
  'privacy.back': 'Tillbaka',

  'review.exampleTitle': 'Enheter och samband',
  'review.exampleBody': '<h1>Enheter och samband</h1><div class="card"><p class="big">sträcka = hastighet × tid</p></div><p>Vilken enhet mäter sträcka?</p><ot-answer id="unit" label="Ditt svar"></ot-answer>',
  'review.exampleCaption': 'Vi börjar med vad vi vet.',
  'review.preparing': 'Förbereder tavlan',
} as const;

export type SvKey = keyof typeof sv;

export function t(key: SvKey, vars?: Record<string, string | number>): string {
  let out: string = sv[key];
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      out = out.replace(`{${k}}`, String(v));
    }
  }
  return out;
}
