CREATE SCHEMA IF NOT EXISTS research_ambush;

CREATE TABLE IF NOT EXISTS research_ambush.ambush_valley_chart_case_v1 (
    chart_case_id TEXT PRIMARY KEY,
    canonical_symbol TEXT NOT NULL,
    stock_name TEXT,
    case_trade_date DATE NOT NULL,
    case_source TEXT NOT NULL,
    case_status TEXT NOT NULL DEFAULT 'pending_labeling',
    label_mode_allowed TEXT NOT NULL DEFAULT 'both',
    as_of_date DATE,
    valley_low_date DATE,
    turn_anchor_date DATE,
    source_data_version TEXT,
    model_version TEXT,
    feature_version TEXT,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    dynamic_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    daily_bar_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    weekly_bar_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    automatic_feature_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ambush_valley_chart_case_status_v1 CHECK (
        case_status IN ('pending_labeling','labeled','review_required','approved','archived','data_blocked')
    ),
    CONSTRAINT ck_ambush_valley_chart_label_mode_allowed_v1 CHECK (
        label_mode_allowed IN ('as_of','outcome_review','both')
    )
);

CREATE INDEX IF NOT EXISTS idx_ambush_valley_chart_case_symbol_day_v1
    ON research_ambush.ambush_valley_chart_case_v1(canonical_symbol, case_trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_ambush_valley_chart_case_status_v1
    ON research_ambush.ambush_valley_chart_case_v1(case_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_ambush.ambush_valley_manual_label_v1 (
    manual_label_id TEXT PRIMARY KEY,
    chart_case_id TEXT NOT NULL REFERENCES research_ambush.ambush_valley_chart_case_v1(chart_case_id) ON DELETE CASCADE,
    labeler_id TEXT NOT NULL,
    labeler_role TEXT,
    label_mode TEXT NOT NULL,
    valley_structure_label TEXT,
    turn_timing_label TEXT,
    sample_role_label TEXT,
    outcome_label TEXT,
    manual_label_confidence TEXT NOT NULL DEFAULT 'medium',
    manual_label_note TEXT,
    visible_feature_boundary JSONB NOT NULL DEFAULT '{}'::jsonb,
    label_version TEXT NOT NULL DEFAULT 'ambush_valley_manual_label_v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ambush_valley_manual_label_mode_v1 CHECK (label_mode IN ('as_of','outcome_review')),
    CONSTRAINT ck_ambush_valley_manual_confidence_v1 CHECK (manual_label_confidence IN ('high','medium','low')),
    CONSTRAINT ck_ambush_valley_manual_as_of_no_outcome_v1 CHECK (
        label_mode <> 'as_of' OR outcome_label IS NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_ambush_valley_manual_label_case_v1
    ON research_ambush.ambush_valley_manual_label_v1(chart_case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ambush_valley_manual_label_mode_v1
    ON research_ambush.ambush_valley_manual_label_v1(label_mode, created_at DESC);

CREATE TABLE IF NOT EXISTS research_ambush.ambush_valley_manual_label_tag_v1 (
    manual_label_tag_id TEXT PRIMARY KEY,
    manual_label_id TEXT NOT NULL REFERENCES research_ambush.ambush_valley_manual_label_v1(manual_label_id) ON DELETE CASCADE,
    tag_group TEXT NOT NULL,
    tag_code TEXT NOT NULL,
    tag_value TEXT NOT NULL DEFAULT 'true',
    tag_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ambush_valley_manual_label_tag_label_v1
    ON research_ambush.ambush_valley_manual_label_tag_v1(manual_label_id, tag_group, tag_code);

CREATE TABLE IF NOT EXISTS research_ambush.ambush_valley_label_taxonomy_v1 (
    taxonomy_id TEXT PRIMARY KEY,
    tag_group TEXT NOT NULL,
    tag_code TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    tag_description TEXT,
    allowed_label_mode TEXT NOT NULL DEFAULT 'both',
    is_positive_signal BOOLEAN NOT NULL DEFAULT false,
    is_negative_signal BOOLEAN NOT NULL DEFAULT false,
    is_hard_negative_signal BOOLEAN NOT NULL DEFAULT false,
    is_training_eligible BOOLEAN NOT NULL DEFAULT false,
    enabled BOOLEAN NOT NULL DEFAULT true,
    display_order INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ambush_valley_label_taxonomy_code_v1 UNIQUE(tag_group, tag_code),
    CONSTRAINT ck_ambush_valley_label_taxonomy_mode_v1 CHECK (allowed_label_mode IN ('as_of','outcome_review','both'))
);

CREATE INDEX IF NOT EXISTS idx_ambush_valley_label_taxonomy_enabled_v1
    ON research_ambush.ambush_valley_label_taxonomy_v1(enabled, display_order, tag_group);

CREATE TABLE IF NOT EXISTS research_ambush.ambush_valley_label_review_v1 (
    review_id TEXT PRIMARY KEY,
    chart_case_id TEXT NOT NULL REFERENCES research_ambush.ambush_valley_chart_case_v1(chart_case_id) ON DELETE CASCADE,
    manual_label_id TEXT REFERENCES research_ambush.ambush_valley_manual_label_v1(manual_label_id) ON DELETE SET NULL,
    reviewer_id TEXT NOT NULL,
    review_status TEXT NOT NULL,
    review_comment TEXT,
    final_sample_role_label TEXT,
    final_outcome_label TEXT,
    final_label_confidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ambush_valley_label_review_status_v1 CHECK (review_status IN ('approved','rejected','needs_discussion')),
    CONSTRAINT ck_ambush_valley_label_review_confidence_v1 CHECK (
        final_label_confidence IS NULL OR final_label_confidence IN ('high','medium','low')
    )
);

CREATE INDEX IF NOT EXISTS idx_ambush_valley_label_review_case_v1
    ON research_ambush.ambush_valley_label_review_v1(chart_case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS research_ambush.ambush_valley_pattern_library_member_v1 (
    library_member_id TEXT PRIMARY KEY,
    chart_case_id TEXT NOT NULL REFERENCES research_ambush.ambush_valley_chart_case_v1(chart_case_id) ON DELETE CASCADE,
    manual_label_id TEXT REFERENCES research_ambush.ambush_valley_manual_label_v1(manual_label_id) ON DELETE SET NULL,
    library_role TEXT NOT NULL,
    pattern_family TEXT,
    training_split TEXT NOT NULL DEFAULT 'review_only',
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    shape_signature_id TEXT,
    feature_snapshot_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ambush_valley_library_role_v1 CHECK (
        library_role IN ('positive_prototype','hard_negative','missed_opportunity','control','research_only')
    ),
    CONSTRAINT ck_ambush_valley_training_split_v1 CHECK (
        training_split IN ('train','validation','test','review_only')
    )
);

CREATE INDEX IF NOT EXISTS idx_ambush_valley_library_member_case_v1
    ON research_ambush.ambush_valley_pattern_library_member_v1(chart_case_id, library_role);

INSERT INTO research_ambush.ambush_valley_label_taxonomy_v1 (
    taxonomy_id, tag_group, tag_code, tag_name, tag_description,
    allowed_label_mode, is_positive_signal, is_negative_signal,
    is_hard_negative_signal, is_training_eligible, display_order
) VALUES
    ('taxonomy:structure:mature_valley', 'structure', 'MATURE_VALLEY', '低谷成熟', '回撤、缩量和支撑状态已经具备低谷样本价值。', 'both', true, false, false, true, 10),
    ('taxonomy:structure:immature_valley', 'structure', 'IMMATURE_VALLEY', '低谷未成熟', '下跌或整理仍未充分，暂不适合进入正样本库。', 'both', false, true, false, false, 20),
    ('taxonomy:support:support_intact', 'support', 'SUPPORT_INTACT', '支撑未破', '关键低点或箱体支撑保持有效。', 'as_of', true, false, false, true, 30),
    ('taxonomy:support:support_broken', 'support', 'SUPPORT_BROKEN', '支撑破坏', '关键支撑被有效跌破，需要进入风险或负样本观察。', 'both', false, true, true, true, 40),
    ('taxonomy:compression:box_compression', 'compression', 'BOX_COMPRESSION', '横盘压缩', '低点后进入窄幅横盘压缩，具备后续重启研究价值。', 'both', true, false, false, true, 50),
    ('taxonomy:turn:day1_day2_turn', 'turn', 'DAY1_DAY2_TURN', '刚抬头', '低谷后的第一天或第二天出现有效抬头。', 'as_of', true, false, false, true, 60),
    ('taxonomy:turn:late_rebound', 'turn', 'LATE_REBOUND', '抬头偏晚', '低点后已经反弹多日，不能冒充刚抬头。', 'both', false, true, false, false, 70),
    ('taxonomy:risk:false_rebound', 'risk', 'FALSE_REBOUND', '假反弹', '形态像抬头但后续承接不足或回落明显。', 'outcome_review', false, true, true, true, 80),
    ('taxonomy:risk:hard_negative', 'risk', 'HARD_NEGATIVE', '硬负样本', '数值或形态接近正样本但结果失败，需要单独沉淀。', 'outcome_review', false, true, true, true, 90),
    ('taxonomy:entry:entry_window_clear', 'entry', 'ENTRY_WINDOW_CLEAR', '买点窗口清晰', '存在可解释且可交易的观察窗口。', 'outcome_review', true, false, false, true, 100),
    ('taxonomy:entry:price_success_untradable', 'entry', 'PRICE_SUCCESS_UNTRADABLE', '涨了但不好买', '价格结果成功，但可交易窗口不足。', 'outcome_review', false, true, false, true, 110)
ON CONFLICT (tag_group, tag_code) DO UPDATE SET
    tag_name = EXCLUDED.tag_name,
    tag_description = EXCLUDED.tag_description,
    allowed_label_mode = EXCLUDED.allowed_label_mode,
    is_positive_signal = EXCLUDED.is_positive_signal,
    is_negative_signal = EXCLUDED.is_negative_signal,
    is_hard_negative_signal = EXCLUDED.is_hard_negative_signal,
    is_training_eligible = EXCLUDED.is_training_eligible,
    enabled = true,
    display_order = EXCLUDED.display_order;

-- Guardrails:
-- 1. research_ambush is append-only research asset storage and must not write official signals.
-- 2. as_of labels cannot carry outcome labels or outcome-only taxonomy tags.
-- 3. Manual labels can support pattern library research only after review; they do not change model scores.
-- 4. Dynamic feature gaps remain explicit JSON arrays; missing dynamic snapshots must not be filled with mock values.
