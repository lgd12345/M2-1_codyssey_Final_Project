-- Operators rate the AI analysis they reviewed. One rating per person per analysis; a re-analysis is a new row
-- in service_analysis and therefore starts without ratings, while the earlier ratings stay with what they judged.
CREATE TABLE service_analysis_feedback (
    analysis_id UUID NOT NULL REFERENCES service_analysis(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES app_user(id),
    rating TEXT NOT NULL CHECK (rating IN ('helpful', 'not_helpful')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (analysis_id, user_id)
);
