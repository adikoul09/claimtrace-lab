import { test } from "node:test";
import assert from "node:assert/strict";
import { configKeyLabel, metricLabel } from "./labels.ts";

test("metricLabel turns logged metric names into plain words", () => {
  assert.equal(metricLabel("final_student_distilled_test_errors"), "Student distilled test errors");
  assert.equal(metricLabel("final_teacher_wall_s"), "Teacher wall time (s)");
  assert.equal(metricLabel("train_loss"), "Train loss");
  assert.equal(metricLabel("acc"), "Acc");
});

test("configKeyLabel names common CONFIG keys and spells out the rest", () => {
  assert.equal(configKeyLabel("lr"), "learning rate");
  assert.equal(configKeyLabel("T"), "temperature");
  assert.equal(configKeyLabel("student.grad_clip"), "student grad clip");
  assert.equal(configKeyLabel("teacher.lr"), "teacher learning rate");
  assert.equal(configKeyLabel("batch_size"), "batch size");
});
