/**
 * Comment thread — SPEC+ (docs/spec-deviations.md). A bottom sheet, not a
 * new full-screen route, so tapping the comment icon on a feed card's rail
 * never navigates away from the feed — matches how Instagram/TikTok keep
 * you in place while you read or add a comment.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { deleteComment, fetchComments, postComment } from '../api/client';
import type { Comment } from '../api/types';
import { colors, radius, space, type, weight } from '../theme';

interface Props {
  outfitId: string;
  visible: boolean;
  onClose: () => void;
  /** Lets the feed card keep its own comment_count in sync without a refetch. */
  onCountChange: (delta: number) => void;
}

export function CommentSheet({ outfitId, visible, onClose, onCountChange }: Props): React.ReactElement {
  const [items, setItems] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const page = await fetchComments(outfitId);
      setItems(page.items);
      setError(null);
    } catch {
      setError('Could not load comments.');
    } finally {
      setLoading(false);
    }
  }, [outfitId]);

  useEffect(() => {
    if (visible) void load();
  }, [visible, load]);

  const send = async (): Promise<void> => {
    const body = draft.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      const comment = await postComment(outfitId, body);
      setItems((existing) => [...existing, comment]);
      setDraft('');
      onCountChange(1);
    } catch {
      setError('Could not post that comment. Try again.');
    } finally {
      setSending(false);
    }
  };

  const remove = async (commentId: string): Promise<void> => {
    setItems((existing) => existing.filter((item) => item.comment_id !== commentId));
    onCountChange(-1);
    try {
      await deleteComment(outfitId, commentId);
    } catch {
      void load();
      onCountChange(1);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="Close comments" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.sheetWrap}
      >
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <Text style={styles.title}>Comments</Text>

          {error ? <Text style={styles.error}>{error}</Text> : null}

          {loading ? (
            <ActivityIndicator color={colors.textMuted} style={styles.spinner} />
          ) : (
            <FlatList
              data={items}
              keyExtractor={(item) => item.comment_id}
              style={styles.list}
              ListEmptyComponent={
                <Text style={styles.empty}>No comments yet — be the first to say something.</Text>
              }
              renderItem={({ item }) => (
                <View style={styles.row}>
                  <View style={styles.rowBody}>
                    <Text style={styles.author}>{item.author_display_name}</Text>
                    <Text style={styles.body}>{item.body}</Text>
                  </View>
                  {item.is_mine ? (
                    <Pressable
                      onPress={() => void remove(item.comment_id)}
                      accessibilityRole="button"
                      accessibilityLabel="Delete comment"
                      hitSlop={8}
                    >
                      <Text style={styles.remove}>Delete</Text>
                    </Pressable>
                  ) : null}
                </View>
              )}
            />
          )}

          <View style={styles.composerRow}>
            <TextInput
              style={styles.input}
              placeholder="Add a comment"
              placeholderTextColor={colors.textMuted}
              value={draft}
              onChangeText={setDraft}
              maxLength={500}
              multiline
            />
            <Pressable
              onPress={() => void send()}
              disabled={!draft.trim() || sending}
              accessibilityRole="button"
              accessibilityLabel="Post comment"
            >
              <Text style={[styles.send, (!draft.trim() || sending) && styles.sendDisabled]}>Post</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)' },
  sheetWrap: { justifyContent: 'flex-end' },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    paddingBottom: space.lg,
    maxHeight: '75%',
    minHeight: '45%',
  },
  handle: {
    alignSelf: 'center',
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    marginBottom: space.sm,
  },
  title: { ...type.bodyMedium, color: colors.text, marginBottom: space.sm },
  spinner: { marginTop: space.xl },
  list: { flexGrow: 0 },
  empty: { ...type.body, color: colors.textMuted, paddingVertical: space.lg },
  error: { ...type.meta, color: colors.systemError, marginBottom: space.sm },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    paddingVertical: space.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowBody: { flex: 1, paddingRight: space.sm },
  author: { ...type.meta, color: colors.text, fontWeight: weight.medium },
  body: { ...type.body, color: colors.text, marginTop: 2 },
  remove: { ...type.meta, color: colors.textMuted },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    marginTop: space.sm,
    gap: space.sm,
  },
  input: {
    flex: 1,
    ...type.body,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    maxHeight: 100,
  },
  send: { ...type.bodyMedium, color: colors.accent, fontWeight: weight.medium, paddingVertical: space.sm },
  sendDisabled: { color: colors.textMuted },
});
