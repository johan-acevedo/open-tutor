// Bounds shared by validation and layout. Mirror server/open_tutor/board.py (DIAGRAM_*).

export const DIAGRAM_MAX_NODES = 24;
export const DIAGRAM_MAX_LINKS = 40;
export const DIAGRAM_COORD_LIMIT = 4000;
export const DIAGRAM_ID = /^[A-Za-z0-9_-]{1,24}$/;
export const DIAGRAM_ROLES = ['center', 'idea', 'step', 'result', 'note'] as const;
